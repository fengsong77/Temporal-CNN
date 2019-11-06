## simple TCN without gating and skip connections, with both numeric and categorical features for the past, and with categorical features for the future


import mxnet as mx
from mxnet import gluon,nd,ndarray
from mxnet.gluon import nn

def _reshape_like(F, x, y):
    """Reshapes x to the same shape as y."""
    return x.reshape(y.shape) if F is ndarray else F.reshape_like(x, y)

def _apply_weighting(F, loss, weight=None, sample_weight=None):
    if sample_weight is not None:
        loss = F.broadcast_mul(loss, sample_weight)

    if weight is not None:
        assert isinstance(weight, numeric_types), "weight must be a number"
        loss = loss * weight

    return loss

class Loss(nn.HybridBlock):
    def __init__(self, weight, batch_axis, **kwargs):
        super(Loss, self).__init__(**kwargs)
        self._weight = weight
        self._batch_axis = batch_axis

    def __repr__(self):
        s = '{name}(batch_axis={_batch_axis}, w={_weight})'
        return s.format(name=self.__class__.__name__, **self.__dict__)

    def hybrid_forward(self, F, x, *args, **kwargs):
        raise NotImplementedError
        
class QuantileLoss(Loss):
    def __init__(self,quantile_alpha=0.5, weight=None, batch_axis=1, **kwargs):
        super(QuantileLoss, self).__init__(weight, batch_axis, **kwargs)
        self.quantile_alpha = quantile_alpha

    def hybrid_forward(self, F, pred, label, sample_weight=None):
        label = _reshape_like(F, label, pred)
        I = pred<=label
        loss = self.quantile_alpha*(label-pred)*I+(1-self.quantile_alpha)*(pred-label)*(1-I)
        #print('loss1',loss)
        loss = _apply_weighting(F, loss, self._weight, sample_weight)
        #print('loss2',loss)
        return F.sum(loss, axis=self._batch_axis)


class ResidualTCN(nn.Block):
    def __init__(self,d, n_residue=1, k=2,  **kwargs):
        super(ResidualTCN, self).__init__(**kwargs)
        self.conv1 = nn.Conv1D(in_channels=n_residue, channels=n_residue, kernel_size=k, dilation=d)
        self.bn1 = nn.BatchNorm()
        self.conv2 = nn.Conv1D(in_channels=n_residue, channels=n_residue, kernel_size=k, dilation=d)
        self.bn2 = nn.BatchNorm()
        
    def forward(self, x):
        out = nd.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        return nd.relu(out+x[:,:,-out.shape[2]:])
    
    
class ResidualTCN2(nn.Block):
    def __init__(self,d, n_residue=1, k=2,  **kwargs):
        super(ResidualTCN2, self).__init__(**kwargs)
        self.conv1 = nn.Conv1D(in_channels=n_residue, channels=n_residue, kernel_size=k, dilation=d)
        self.bn1 = nn.BatchNorm()
        self.conv2 = nn.Conv1D(in_channels=n_residue, channels=n_residue, kernel_size=k, dilation=d)
        self.bn2 = nn.BatchNorm()

    def forward(self, x):
        out = nd.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        return nd.relu(out)+x[:,:,-out.shape[2]:]
     

class Residual(nn.HybridBlock):
    def __init__(self, xDim,  **kwargs):
        super(Residual, self).__init__(**kwargs)
        self.fc1 = nn.Dense(64, flatten=False)
        self.bn1 = nn.BatchNorm(axis=2)
        self.fc2 = nn.Dense(units=xDim, flatten=False)
        self.bn2 = nn.BatchNorm(axis=2)

    def hybrid_forward(self,F, x):
        out = nd.relu(self.bn1(self.fc1(x)))
        out = self.bn2(self.fc2(out))
        return nd.relu(out + x)

    
    
class TCN(nn.Block):
    def __init__(self, dilation_depth=2, n_repeat=5, **kwargs):
        super(TCN, self).__init__(**kwargs)
        self.dilations = [1,2]
        self.conv_sigmoid = nn.Sequential()
        self.net=nn.Sequential()
        #self.bn = nn.BatchNorm()
        self.post_res= nn.Sequential()
        self.TCN= nn.Sequential()
        with self.name_scope():
            ## The embedding part
            self.id_embedding=nn.Embedding(1237,6)
            self.nYear_embedding = nn.Embedding(3,2)
            self.nMonth_embedding = nn.Embedding(12,2)
            for d in self.dilations:
                self.TCN.add(ResidualTCN2(d=d))
            self.post_res.add(Residual(xDim=16))
            #self.net.add(nn.Dense(64, flatten=False))
            self.net.add(nn.BatchNorm(axis=2))
            self.net.add(nn.Activation(activation='relu'))
            self.net.add(nn.Dropout(.2))
            #self.net.add(nn.Dense(1,flatten=False))
            self.mu = nn.Dense(1, flatten=False)
            self.sigma = nn.Dense(1, flatten=False, activation='softrelu')   
            

    def forward(self, x_num, x_cat):
        # preprocess
        embed_concat = nd.concat(
            self.id_embedding(x_cat[:,:,0]),
            self.nYear_embedding(x_cat[:,:,1]),
            self.nMonth_embedding(x_cat[:,:,2]), dim=2)
        output = self.preprocess(x_num)
        for sub_TCN in self.TCN:
            output = self.residue_forward(output, sub_TCN)
        #output=nd.transpose(output, axes=(0,2,1))
        #print(output.shape)
        output = nd.broadcast_axis(output, axis=1, size=12)
        post_concat = nd.concat(output, embed_concat, dim=2)
        output=self.net(self.post_res(post_concat))
        #
        output_mu = self.mu(output)
        output_mu = output_mu.reshape(output_mu.shape[0],-1)
        output_sigma = self.sigma(output)
        output_sigma = output_sigma.reshape(output_sigma.shape[0],-1)
        return output_mu, output_sigma
    
    def residue_forward(self, x, sub_TCN):
        return sub_TCN(x)
    
    def preprocess(self, x):
        ##The shape of the input tensor
        shape0, shape1 = x.shape
        output = x.reshape((shape0, 1, shape1))
        return output
