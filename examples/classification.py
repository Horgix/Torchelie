import sys
import argparse

import crayons

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import Adam
from torchelie.optim import *

from torchvision.datasets import MNIST, CIFAR10
import torchvision.transforms as TF

import torchelie.nn as tnn
import torchelie.models
from torchelie.models import VggDebug, ResNetDebug, PreactResNetDebug
from torchelie.utils import nb_parameters
from torchelie.recipes.classification import CrossEntropyClassification

parser = argparse.ArgumentParser()
parser.add_argument('--cpu', action='store_true')
parser.add_argument('--dataset',
                    type=str,
                    choices=['mnist', 'cifar10'],
                    default='mnist')
parser.add_argument('--models', default='all')
parser.add_argument('--shapes-only', action='store_true')
parser.add_argument('--epochs', default=1, type=int)
opts = parser.parse_args()

device = 'cpu' if opts.cpu else 'cuda'

def ThreeChannels(x):
    return x.expand(3, -1, -1).clone()

tfms = TF.Compose([TF.Resize(32), TF.ToTensor(),
        ThreeChannels,
        TF.Normalize([0.5] * 3, [0.5] * 3, True),
    ])
train_tfms = TF.Compose([
        TF.Pad(4),
        TF.RandomCrop(32),
        TF.ColorJitter(0.5, 0.5, 0.4, 0.05),
        TF.RandomHorizontalFlip(),
        TF.ToTensor(),
        ThreeChannels,
        TF.Normalize([0.5] * 3, [0.5] * 3, True),
    ])
if opts.dataset == 'mnist':
    ds = MNIST('~/.cache/torch/mnist/', download=True, transform=train_tfms)
    dst = MNIST('~/.cache/torch/mnist/', download=True, transform=tfms, train=False)
    CH=1
if opts.dataset == 'cifar10':
    ds = CIFAR10('~/.cache/torch/cifar10', download=True, transform=train_tfms)
    dst = CIFAR10('~/.cache/torch/cifar10', download=True, transform=tfms, train=False)
    CH=3
dl = torch.utils.data.DataLoader(ds,
                                 num_workers=4,
                                 batch_size=256,
                                 shuffle=True)
dlt = torch.utils.data.DataLoader(dst,
                                  num_workers=4,
                                  batch_size=256,
                                  shuffle=True)
if opts.models == 'all':
    nets = [#VggDebug,
            ResNetDebug, PreactResNetDebug]
else:
    nets = [torchelie.models.__dict__[m] for m in opts.models.split(',')]


def summary(Net):
    clf = Net(10, in_ch=CH, debug=True)
    clf(torch.randn(32, CH, 32, 32))
    print('Nb parameters: {}'.format(nb_parameters(clf)))


def train_net(Net):
    clf = Net(10, in_ch=CH)
    clf = torchelie.models.Classifier( torchelie.models.Attention56Bone(), 2048, 10)
    #clf = torchelie.models.EfficientNet(CH, 10, B=0)
    print(clf)

    clf_recipe = CrossEntropyClassification(clf,
                                            dl,
                                            dlt,
                                            ds.classes,
                                            lr=0.01,
                                            beta1=0.8,
                                            log_every=10,
                                            wd=0.1,
                                            test_every=50,
                                            visdom_env='example_clf')

    clf_recipe.to(device)
    acc = clf_recipe.run(opts.epochs)['test_metrics']['acc']

    if acc > 0.90:
        print(crayons.green('PASS ({})'.format(acc), bold=True))
    else:
        print(crayons.red('FAILURE ({})'.format(acc), bold=True))


for Net in nets:
    print(crayons.yellow('---------------------------------'))
    print(crayons.yellow('-- ' + Net.__name__))
    print(crayons.yellow('---------------------------------'))

    if opts.shapes_only:
        summary(Net)
    else:
        train_net(Net)
