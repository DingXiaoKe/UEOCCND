# Copyright 2018 Stanislav Pidhorskyi
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#  http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
from __future__ import print_function
import torch.utils.data
from torch import optim
from torchvision.utils import save_image
from net_cifar import *
import torch.nn.functional as F
from torch.autograd import Variable
import numpy as np
import json
import pickle
import time
import random
import os
import torchvision
import torchvision.transforms as transforms
import torchvision.datasets as datasets
from torchvision.datasets import MNIST
from torchvision.datasets import CIFAR10,CIFAR100
from torchvision.datasets import ImageFolder
import torchvision.transforms as transforms
from sklearn.metrics import roc_auc_score
from evaluate import evaluate
from sklearn.metrics import roc_curve

use_cuda = torch.cuda.is_available()

FloatTensor = torch.FloatTensor
IntTensor = torch.IntTensor
LongTensor = torch.LongTensor
torch.set_default_tensor_type('torch.FloatTensor')

if use_cuda:
    device = torch.cuda.current_device()
    torch.set_default_tensor_type('torch.cuda.FloatTensor')
    FloatTensor = torch.cuda.FloatTensor
    IntTensor = torch.cuda.IntTensor
    LongTensor = torch.cuda.LongTensor
    print("Running on ", torch.cuda.get_device_name(device))

def setup(x):
    if use_cuda:
        return x.cuda()
    else:
        return x.cpu()


def numpy2torch(x):
    return setup(torch.from_numpy(x))

def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        m.weight.data.normal_(0.0, 0.02)
    elif classname.find('BatchNorm') != -1:
        m.weight.data.normal_(1.0, 0.02)
        m.bias.data.fill_(0)

def extract_batch(data, it, batch_size):
    x = numpy2torch(data[it * batch_size:(it + 1) * batch_size, :, :]) / 255.0
    #x.sub_(0.5).div_(0.5)
    return Variable(x)

def Cutout(n_holes, length,train_set,train_label):
    # print(len(train_set))
    train = []
    label = []

    for i,img in enumerate(train_set):
        p = random.random()
        # print(p)
        if p > 0.5:
            h = img.shape[0]
            w = img.shape[1]
            c = img.shape[2]
            mask = np.ones((h, w, c), np.float32)

            for n in range(n_holes):
                y = np.random.randint(h)
                x = np.random.randint(w)
                y1 = np.clip(y - length // 2, 0, h)
                y2 = np.clip(y + length // 2, 0, h)
                x1 = np.clip(x - length // 2, 0, w)
                x2 = np.clip(x + length // 2, 0, w)
                mask[y1: y2, x1: x2, :] = 0.

            mask = torch.from_numpy(mask)
            img = torch.from_numpy(img)
            mask = mask.expand_as(img)
            img = img * mask
            img = img.numpy()
            train.append(img)
            ## cutout label = 0 false label
            label.append(1.)
        else: 
            train.append(img)
            ## not cutout label = 1 true label
            label.append(1.)
    train = np.array(train)
    label = np.array(label)
    # print(label)
    return train,label

def load(dataset,batch_size,flag,isize):
    # print(dataset)
    if dataset == "Cifar10" and flag == 1:
        transform = transforms.Compose(
            [
                transforms.Scale(isize),
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
            ]
        )
        dataset = CIFAR10(root='./data/cifar10', train=True, download=True, transform=transform)
        dataloader = torch.utils.data.DataLoader(dataset,batch_size=batch_size,shuffle=True,num_workers=8,drop_last=True)
        # print(len(trainloader))
        return dataloader
    if dataset == "Cifar100" and flag == 1:
        transform = transforms.Compose(
            [
                transforms.Scale(isize),
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
            ]
        )
        dataset = CIFAR100(root='./data/cifar100', train=True, download=True, transform=transform)
        dataloader = torch.utils.data.DataLoader(dataset,batch_size=batch_size,shuffle=True,num_workers=8,drop_last=True)
        # print(len(trainloader))
        return dataloader

    if dataset == "Cifar10" and flag == 0:
        transform = transforms.Compose(
            [
                transforms.Scale(32),
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
            ]
        )
        dataset = CIFAR10(root='./data/cifar10', train=False, download=True, transform=transform)
        dataloader = torch.utils.data.DataLoader(dataset,batch_size=batch_size,shuffle=True,num_workers=8,drop_last=True)
        return dataloader
    
    if dataset == "Cifar100" and flag == 0:
        transform = transforms.Compose(
            [
                transforms.Scale(isize),
                transforms.ToTensor(),
                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
            ]
        )
        dataset = CIFAR100(root='./data/cifar100', train=False, download=True, transform=transform)
        dataloader = torch.utils.data.DataLoader(dataset,batch_size=batch_size,shuffle=True,num_workers=8,drop_last=True)
        return dataloader

    if dataset != "Uniform" and dataset != "Gaussian":
        transform = transforms.Compose(
            [
            transforms.ToTensor(),
            transforms.Normalize((125.3/255, 123.0/255, 113.9/255), (63.0/255, 62.1/255.0, 66.7/255.0)),
            ]
        )
        dataset = torchvision.datasets.ImageFolder("./data/{}/".format(dataset), transform=transform)
        dataloader = torch.utils.data.DataLoader(dataset, batch_size=batch_size,shuffle=True, num_workers=2,drop_last=True)
        return dataloader

def train(trainset,batch_size):
    lambd = 0.1
    zsize = 100
    cutout = True # whether cover the img
    n_holes = 1 # number of holes to cut out from image
    length = 16 # length of the holes
    TINY = 1e-15
    train_epoch = 25
    lr = 0.001
    train_len = len(trainset)
    G = Generator(zsize, channels=3)
    setup(G)
    G.apply(weights_init)

    D = Discriminator(channels=3)
    setup(D)
    D.apply(weights_init)

    P = PDense(1, 128, 2)
    setup(P)
    P.weight_init(mean=0, std=0.01)

    C = Dense(1, 128, 1, batch_size)
    setup(C)
    C.weight_init(mean=0, std=0.01)

    E = Encoder(zsize, channels=3)
    setup(E)
    E.apply(weights_init)

    ZD = ZDiscriminator(zsize, batch_size)
    setup(ZD)
    ZD.apply(weights_init)

    

    G_optimizer = optim.Adam(G.parameters(), lr=lr, betas=(0.5, 0.9))
    D_optimizer = optim.Adam(list(D.parameters())\
                            +list(P.parameters())\
                            +list(C.parameters()), lr=lr, betas=(0.5, 0.9))
    E_optimizer = optim.Adam(E.parameters(), lr=lr, betas=(0.5, 0.9))
    GE_optimizer = optim.Adam(list(E.parameters()) + list(G.parameters()), lr=lr, betas=(0.5, 0.9))
    ZD_optimizer = optim.Adam(ZD.parameters(), lr=lr, betas=(0.5, 0.9))

    BCE_loss = nn.BCELoss()
    MSE_loss = nn.MSELoss()
    y_real_ = torch.ones(batch_size)
    y_fake_ = torch.zeros(batch_size)
    
    y_real_z = torch.ones(batch_size)
    y_fake_z = torch.zeros(batch_size)

    for epoch in range(train_epoch):
        G.train()
        D.train()
        P.train()
        C.train()
        E.train()
        ZD.train()
        epoch_start_time = time.time()
        
        for it,data in enumerate(trainset):
            #############################################
            x, labels = data
            x, labels = Cutout(n_holes, length, np.asarray(x), np.asarray(labels))
            x = Variable(torch.from_numpy(x))
            x = x.cuda()

            binary_class_y_real = torch.zeros(batch_size, 2)
            for i in range(batch_size):
                binary_class_y_real[i][0] = 0.99
                binary_class_y_real[i][1] = 0.01
            
            binary_class_y_fake = torch.zeros(batch_size, 2)
            for i in range(batch_size):
                binary_class_y_fake[i][0] = 0.101
                binary_class_y_fake[i][1] = 0.99

            #############################################

            ZD.zero_grad()
            E.zero_grad()

            z = torch.randn((batch_size, zsize)).view(-1, zsize)
            z = Variable(z)
            ZD_result = ZD(z).squeeze()
            ZD_real_loss = BCE_loss(ZD_result, y_real_z )

            z = E(x).squeeze().detach().view(-1, zsize)
            ZD_result = ZD(z).squeeze()
            ZD_fake_loss = BCE_loss(ZD_result, y_fake_z)

            ZD_train_loss = ZD_real_loss + ZD_fake_loss
            ZD_train_loss.backward()

            ZD_optimizer.step()

            #############################################

            E.zero_grad()
            G.zero_grad()

            z = E(x).view(-1, zsize, 1, 1)
            x_d = G(z)

            ZD_result = ZD(z.squeeze()).squeeze()

            E_loss = BCE_loss(ZD_result, y_real_z ) * 2.0
            x_d.type(torch.FloatTensor)
            x.type(torch.FloatTensor)
        
            Recon_loss = MSE_loss(x_d, x)
            Recon_loss.backward(retain_graph=True)
            E_loss.backward(retain_graph=True)
            GE_optimizer.step()
            #############################################
            for i in range(1):
                D.zero_grad()
                G.zero_grad()
                E.zero_grad()
                # TODO
                D_real, _ = D(x)
                D_real = D_real.reshape((batch_size, 1))
                z = E(x).view(-1, zsize, 1, 1)
                x_fake = G(z).detach()
                D_fake, _ = D(x_fake)
                D_fake = D_fake.reshape((batch_size, 1))
                    
                _, P_real = P(D_real)
                _, C_real = C(D_real)
                eps = 1e-12
                P_real = torch.clamp(P_real, 0. + eps, 1. - eps)
                C_real = torch.clamp(C_real, 0. + eps, 1. - eps)
                b = Variable(torch.bernoulli(torch.Tensor(C_real.size()).uniform_(0, 1))).cuda()
                C_real = C_real * b + (1 - b)
                P_real_prim = P_real * C_real + (1. - C_real) * binary_class_y_real
                D_real_loss = torch.sum(- torch.log(P_real_prim + TINY) * binary_class_y_real, 1).reshape((batch_size, 1))\
                                - lambd * torch.log(C_real + TINY)
                
                _, P_fake = P(D_fake)
                _, C_fake = C(D_fake)
                P_fake = torch.clamp(P_fake, 0. + eps, 1. - eps)
                C_fake = torch.clamp(C_fake, 0. + eps, 1. - eps)
                b = Variable(torch.bernoulli(torch.Tensor(C_fake.size()).uniform_(0, 1))).cuda()
                C_fake = C_fake * b + (1 - b)
                P_fake_prim = P_fake * C_fake + (1. - C_fake) * binary_class_y_fake
                D_fake_loss = torch.sum(- torch.log(P_fake_prim + TINY) * binary_class_y_fake, 1).reshape((batch_size, 1))\
                                - lambd * torch.log(C_fake + TINY)

                D_train_loss = torch.mean(D_real_loss + TINY) \
                                + torch.mean(D_fake_loss + TINY) 
                D_train_loss.backward()

                D_optimizer.step()

            #############################################
            for i in range(1):
                G.zero_grad()
                E.zero_grad()
                
                z = E(x).view(-1, zsize, 1, 1)
                x_fake = G(z).detach()
                D_result, _  = D(x_fake)
                D_result = D_result.reshape((batch_size, 1))

                _, P_result = P(D_result)
                _, C_result = C(D_result)
                b = Variable(torch.bernoulli(torch.Tensor(C_result.size()).uniform_(0, 1))).cuda()
                C_result = C_result * b + (1 - b)
                P_result_prim = P_result * C_result + (1. - C_result) * binary_class_y_real 
                D_result_loss = torch.sum(- torch.log(P_result_prim + TINY) * binary_class_y_real, 1) \
                                - lambd * torch.log(C_result + TINY)

                G_train_loss = torch.mean(D_result_loss + TINY)#BCE_loss(D_result, y_real_)

                G_train_loss.backward()
                G_optimizer.step()

            z = E(x).view(-1, zsize, 1, 1)
            x_d = G(z)
            

            if it % 80 ==0:
                directory = 'Train/Cifar'
                if not os.path.exists(directory):
                    os.makedirs(directory)
                comparison = torch.cat([x[:4], x_d[:4]])
                save_image(comparison,
                            'Train/Cifar/reconstruction_'+ str(epoch)+'_'+ str(it) + '.png', nrow=4)
                iter_end_time = time.time()
                per_iter_ptime = iter_end_time - epoch_start_time
                print('[%d/%d]-[%d/%d] - ptime: %.2f, Gloss: %.3f, Dloss: %.3f, ZDloss: %.3f, GEloss: %.3f, Eloss: %.3f' % ((epoch + 1), train_epoch,it, train_len, per_iter_ptime, G_train_loss, D_train_loss, ZD_train_loss, Recon_loss, E_loss))
        print("Training finish!... save training results")
        model_dir = os.path.join('Model', 'Cifar')
        if not os.path.isdir(model_dir):
            os.makedirs(model_dir)
        torch.save(G.state_dict(), '{}/Gmodel_epoch{}.pkl'.format(model_dir,str(epoch)))
        torch.save(E.state_dict(), '{}/Emodel_epoch{}.pkl'.format(model_dir,str(epoch)))
        torch.save(D.state_dict(), '{}/Dmodel_epoch{}.pkl'.format(model_dir,str(epoch)))
        torch.save(ZD.state_dict(), '{}/ZDmodel_epoch{}.pkl'.format(model_dir,str(epoch)))
        torch.save(P.state_dict(), '{}/Pmodel_epoch{}.pkl'.format(model_dir,str(epoch)))
        torch.save(C.state_dict(), '{}/Cmodel_epoch{}.pkl'.format(model_dir,str(epoch)))
    return None

def calculate(anomaly_score,label):
    path = "./Test/Cifar"
    #########################################
    # label 1 inlier  label 0 outlier
    pre1 = []
    for i in range(0,len(anomaly_score)):
        if anomaly_score[i][0]> anomaly_score[i][1]:
            pre1.append(1)
        else:
            pre1.append(0)
    roc_auc = evaluate(labels= label, scores= pre1, directory=path, metric='roc')
    prc_auc_in = evaluate(labels= label, scores= pre1, directory=path, metric='auprc')
    TP = 0
    FP = 0
    TN = 0
    FN = 0
    for i in range(len(label)):
        if label[i]==1 and pre1[i] == 1:
            TP = TP + 1
        if label[i]==1 and pre1[i] == 0:
            FN = FN+1
        if label[i]==0 and pre1[i] == 1:
            FP = FP+1
        if label[i]==0 and pre1[i] ==0: 
            TN = TN+1
    TPR_in = TP/(TP+FN)
    FPR_in = FP/(FP+TN)
    
    ##############################new#########################################
    # label 1 outlier  label 0 inlier
    pre2 = []
    for i in range(len(label)):
        label[i] = 1-label[i]
    # print(label)
    for i in range(0,len(anomaly_score)):
        if anomaly_score[i][0]> anomaly_score[i][1]:
            pre2.append(0)
        else:
            pre2.append(1)
    prc_auc_out = evaluate(labels= label, scores= pre2, directory=path, metric='auprc')
    TP = 0
    FP = 0
    TN = 0
    FN = 0
    for i in range(len(label)):
        if label[i]==1 and pre2[i] == 1:
            TP = TP + 1
        if label[i]==1 and pre2[i] == 0:
            FN = FN+1
        if label[i]==0 and pre2[i] == 1:
            FP = FP+1
        if label[i]==0 and pre2[i] ==0: 
            TN = TN+1
    TPR_out = TP/(TP+FN)
    FPR_out = FP/(FP+TN)

    return roc_auc,prc_auc_in,prc_auc_out,TPR_in,FPR_in,TPR_out,FPR_out

def main(flag):
    train_batch_size = 256
    test_batch_size = 32
    isize = 32
    if flag == 1:
        ##train 
        # trainset = 'Cifar100'
        trainset = 'Cifar10'
        trainset = load(trainset,train_batch_size,flag,isize)
        length = len(trainset)
        print("Train set batch number:", length)
        train(trainset,train_batch_size)
if __name__ == '__main__':
    # 1 train 0 test
    main(1)

