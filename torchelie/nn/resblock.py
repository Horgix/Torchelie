import torch
import torch.nn as nn
from .layers import Conv2d, Conv3x3, Conv1x1
from torchelie.utils import kaiming, xavier, normal_init, constant_init
from .condseq import CondSeq
import collections
from typing import List, Tuple, Optional, cast
from .utils import remove_bn


class SEBlock(nn.Module):
    """
    A Squeeze-And-Excite block

    Args:
        in_ch (int): input channels
        reduction (int): channels reduction factor for the hidden number of
            channels
    """
    def __init__(self, in_ch: int, reduction: int = 16) -> None:
        super(SEBlock, self).__init__()
        reduc = in_ch // reduction
        self.proj = nn.Sequential(
            collections.OrderedDict([('pool', nn.AdaptiveAvgPool2d(1)),
                                     ('squeeze', kaiming(Conv1x1(in_ch,
                                                                 reduc))),
                                     ('relu', nn.ReLU(True)),
                                     ('excite', kaiming(Conv1x1(reduc,
                                                                in_ch))),
                                     ('attn', nn.Sigmoid())]))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x * self.proj(x)


def make_resnet_shortcut(in_channels: int, out_channels: int,
                         stride: int) -> CondSeq:
    shortcut = CondSeq()
    if stride != 1:
        shortcut.add_module(
            'pool', nn.AvgPool2d(1 + (stride - 1) * 2, stride, stride // 2))

    if in_channels != out_channels:
        shortcut.add_module(
            'conv', kaiming(Conv1x1(in_channels, out_channels, bias=False)))
        shortcut.add_module('bn', nn.BatchNorm2d(out_channels))
    return shortcut


class ResBlockBottleneck(nn.Module):
    """
    A Residual Block. Skip connection will be added if the number of input and
    output channels don't match or stride > 1 is used.

    Args:
        in_ch (int): input channels
        out_ch (int): output channels
        stride (int): stride
        use_se (bool): whether to use Squeeze-And-Excite after the convolutions
            for a SE-ResBlock
        bottleneck (bool): whether to use the standard block with two 3x3 convs
            or the bottleneck block with 1x1 -> 3x3 -> 1x1 convs.
    """
    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 stride: int = 1) -> None:
        super(ResBlockBottleneck, self).__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.stride = stride

        self.pre = CondSeq()

        self.branch = CondSeq(
            collections.OrderedDict([
                ('conv1', kaiming(Conv1x1(in_channels, in_channels,
                                          bias=False))),
                ('bn1', constant_init(nn.BatchNorm2d(in_channels), 1)),
                ('relu', nn.ReLU(True)),
                ('conv2',
                 kaiming(
                     Conv3x3(in_channels,
                             in_channels,
                             stride=stride,
                             bias=False))),
                ('bn2', constant_init(nn.BatchNorm2d(in_channels), 1)),
                ('relu2', nn.ReLU(True)),
                ('conv3',
                 kaiming(Conv1x1(in_channels, out_channels, bias=False))),
                ('bn3', constant_init(nn.BatchNorm2d(out_channels), 0)),
            ]))

        self.relu = nn.ReLU(True)

        self.shortcut = make_resnet_shortcut(in_channels, out_channels, stride)

        self.post = CondSeq()

    def condition(self, z: torch.Tensor) -> None:
        self.branch.condition(z)
        self.shortcut.condition(z)
        self.pre.condition(z)
        self.post.condition(z)

    def forward(self,
                x: torch.Tensor,
                z: Optional[torch.Tensor] = None) -> torch.Tensor:
        if z is not None:
            self.condition(z)

        x = self.pre(x)
        x = self.relu(self.branch(x).add_(self.shortcut(x)))
        return self.post(x)

    def remove_bn(self) -> 'ResBlockBottleneck':
        remove_bn(self.branch)
        remove_bn(self.shortcut)
        assert isinstance(self.branch.conv3, nn.Conv2d)
        constant_init(self.branch.conv3, 0)

        return self

    def use_se(self) -> 'ResBlockBottleneck':
        self.post.add_module('se', SEBlock(self.in_channels))
        return self

    def to_resnext(self) -> 'ResBlockBottleneck':
        c = self.branch.conv1
        assert isinstance(c, nn.Conv2d)

        self.branch.conv1 = kaiming(
            nn.Conv2d(c.in_channels,
                      c.out_channels * 2,
                      1,
                      bias=c.bias is not None))

        if hasattr(self.branch, 'bn1'):
            self.branch.bn1 = nn.BatchNorm2d(c.out_channels * 2)

        c = self.branch.conv2
        assert isinstance(c, nn.Conv2d)
        self.branch.conv2 = kaiming(
            nn.Conv2d(c.in_channels * 2,
                      c.out_channels * 2,
                      kernel_size=3,
                      padding=1,
                      stride=self.stride,
                      bias=c.bias is not None, groups=32))

        if hasattr(self.branch, 'bn2'):
            self.branch.bn2 = nn.BatchNorm2d(c.out_channels * 2)

        c = self.branch.conv3
        assert isinstance(c, nn.Conv2d)
        self.branch.conv3 = kaiming(
            nn.Conv2d(c.in_channels * 2,
                      c.out_channels,
                      1,
                      bias=c.bias is not None))
        return self

class ResBlock(nn.Module):
    """
    A Residual Block. Skip connection will be added if the number of input and
    output channels don't match or stride > 1 is used.

    Args:
        in_channels (int): input channels
        out_channels (int): output channels
        stride (int): stride
    """
    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 stride: int = 1) -> None:
        super(ResBlock, self).__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.stride = stride

        self.pre = CondSeq()

        self.branch = CondSeq(
            collections.OrderedDict([
                ('conv1',
                 kaiming(
                     Conv3x3(in_channels,
                             out_channels,
                             stride=stride,
                             bias=False))),
                ('bn1', constant_init(nn.BatchNorm2d(out_channels), 1)),
                ('relu', nn.ReLU(True)),
                ('conv2',
                 kaiming(Conv3x3(out_channels, out_channels, bias=False))),
                ('bn2', constant_init(nn.BatchNorm2d(out_channels), 0))
            ]))

        self.shortcut = make_resnet_shortcut(in_channels, out_channels, stride)

        self.relu = nn.ReLU(True)

        self.post = CondSeq()

    def condition(self, z: torch.Tensor) -> None:
        self.branch.condition(z)
        self.shortcut.condition(z)
        self.pre.condition(z)
        self.post.condition(z)

    def forward(self,
                x: torch.Tensor,
                z: Optional[torch.Tensor] = None) -> torch.Tensor:
        if z is not None:
            self.condition(z)

        x = self.pre(x)
        x = self.relu(self.branch(x).add_(self.shortcut(x)))
        return self.post(x)

    def remove_bn(self) -> 'ResBlock':
        remove_bn(self.branch)
        remove_bn(self.shortcut)
        assert isinstance(self.branch.conv2, nn.Conv2d)
        constant_init(self.branch.conv2, 0)
        return self

    def use_se(self) -> 'ResBlock':
        self.post.add_module('se', SEBlock(self.in_channels))
        return self


def make_preact_resnet_shortcut(in_ch: int, out_ch: int,
                                stride: int) -> CondSeq:
    sc: List[Tuple[str, nn.Module]] = []
    if stride != 1:
        sc.append(
            ('pool', nn.AvgPool2d(1 + (stride - 1) * 2, stride, stride // 2)))

    if in_ch != out_ch:
        sc.append(('conv', kaiming(Conv1x1(in_ch, out_ch))))

    return CondSeq(collections.OrderedDict(sc))


class PreactResBlock(nn.Module):
    """
    A Preactivated Residual Block. Skip connection will be added if the number
    of input and output channels don't match or stride > 1 is used.

    Args:
        in_ch (int): input channels
        out_ch (int): output channels
        stride (int): stride
    """
    branch: CondSeq
    shortcut: CondSeq

    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 stride: int = 1) -> None:
        super(PreactResBlock, self).__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.stride = stride

        self.pre = CondSeq()
        self.preact = CondSeq()

        self.branch = CondSeq(
            collections.OrderedDict([
                ('bn1', constant_init(nn.BatchNorm2d(in_channels), 1)),
                ('relu', nn.ReLU(True)),
                ('conv1',
                 kaiming(
                     Conv3x3(in_channels,
                             out_channels,
                             stride=stride,
                             bias=False))),
                ('bn2', constant_init(nn.BatchNorm2d(out_channels), 1)),
                ('relu2', nn.ReLU(True)),
                ('conv2', constant_init(Conv3x3(out_channels, out_channels),
                                        0)),
            ]))

        self.shortcut = make_preact_resnet_shortcut(in_channels, out_channels,
                                                    stride)

        if in_channels != out_channels:
            self.preact_skip()

        self.post = CondSeq()

    def remove_bn(self) -> 'PreactResBlock':
        remove_bn(self.branch)
        remove_bn(self.shortcut)
        remove_bn(self.preact)
        return self

    def condition(self, z: torch.Tensor) -> None:
        self.pre.condition(z)
        self.preact.condition(z)
        self.branch.condition(z)
        self.shortcut.condition(z)
        self.post.condition(z)

    def preact_skip(self) -> 'PreactResBlock':
        if hasattr(self.branch, 'bn1'):
            self.preact.add_module('bn1', cast(nn.Module, self.branch.bn1))
            del self.branch.bn1

        self.preact.add_module('relu', cast(nn.Module, self.branch.relu))
        del self.branch.relu

        return self

    def forward(self,
                x: torch.Tensor,
                z: Optional[torch.Tensor] = None) -> torch.Tensor:
        if z is not None:
            self.condition(z)
        x = self.pre(x)
        x = self.preact(x)
        x = self.shortcut(x) + self.branch(x)
        return self.post(x)

    def use_se(self) -> 'PreactResBlock':
        self.post.add_module('se', SEBlock(self.in_channels))
        return self


class PreactResBlockBottleneck(nn.Module):
    """
    A Preactivated Residual Block. Skip connection will be added if the number
    of input and output channels don't match or stride > 1 is used.

    Args:
        in_ch (int): input channels
        out_ch (int): output channels
        stride (int): stride
    """
    branch: CondSeq
    shortcut: CondSeq

    def __init__(self,
                 in_channels: int,
                 out_channels: int,
                 stride: int = 1) -> None:
        super(PreactResBlockBottleneck, self).__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.stride = stride

        self.pre = CondSeq()
        self.preact = CondSeq()

        self.branch = CondSeq(
            collections.OrderedDict([
                ('bn1', constant_init(nn.BatchNorm2d(in_channels), 1)),
                ('relu', nn.ReLU(True)),
                ('conv1', kaiming(Conv1x1(in_channels, in_channels,
                                          bias=False))),
                ('bn2', constant_init(nn.BatchNorm2d(in_channels), 1)),
                ('relu2', nn.ReLU(True)),
                ('conv2',
                 kaiming(
                     Conv3x3(in_channels,
                             in_channels,
                             stride=stride,
                             bias=False))),
                ('bn3', constant_init(nn.BatchNorm2d(in_channels), 1)),
                ('relu3', nn.ReLU(True)),
                ('conv3', constant_init(Conv1x1(in_channels, out_channels), 0))
            ]))

        self.shortcut = make_preact_resnet_shortcut(in_channels, out_channels,
                                                    stride)

        if in_channels != out_channels:
            self.preact_skip()

        self.post = CondSeq()

    def remove_bn(self) -> 'PreactResBlockBottleneck':
        remove_bn(self.branch)
        remove_bn(self.shortcut)
        remove_bn(self.preact)
        return self

    def condition(self, z: torch.Tensor) -> None:
        self.pre.condition(z)
        self.preact.condition(z)
        self.branch.condition(z)
        self.shortcut.condition(z)
        self.post.condition(z)

    def preact_skip(self) -> 'PreactResBlockBottleneck':
        if hasattr(self.branch, 'bn1'):
            self.preact.add_module('bn1', cast(nn.Module, self.branch.bn1))
            del self.branch.bn1

        self.preact.add_module('relu', cast(nn.Module, self.branch.relu))
        del self.branch.relu

        return self

    def forward(self,
                x: torch.Tensor,
                z: Optional[torch.Tensor] = None) -> torch.Tensor:
        if z is not None:
            self.condition(z)
        x = self.pre(x)
        x = self.preact(x)
        x = self.shortcut(x) + self.branch(x)
        return self.post(x)

    def use_se(self) -> 'PreactResBlockBottleneck':
        self.post.add_module('se', SEBlock(self.in_channels))
        return self

    def to_resnext(self) -> 'PreactResBlockBottleneck':
        c = self.branch.conv1
        assert isinstance(c, nn.Conv2d)

        self.branch.conv1 = kaiming(
            nn.Conv2d(c.in_channels,
                      c.out_channels * 2,
                      1,
                      bias=c.bias is not None))

        if hasattr(self.branch, 'bn2'):
            self.branch.bn2 = nn.BatchNorm2d(c.out_channels * 2)

        c = self.branch.conv2
        assert isinstance(c, nn.Conv2d)
        self.branch.conv2 = kaiming(
            nn.Conv2d(c.in_channels * 2,
                      c.out_channels * 2,
                      kernel_size=3,
                      padding=1,
                      stride=self.stride,
                      bias=c.bias is not None, groups=32))

        if hasattr(self.branch, 'bn3'):
            self.branch.bn3 = nn.BatchNorm2d(c.out_channels * 2)

        c = self.branch.conv3
        assert isinstance(c, nn.Conv2d)
        self.branch.conv3 = kaiming(
            nn.Conv2d(c.in_channels * 2,
                      c.out_channels,
                      1,
                      bias=c.bias is not None))
        return self
