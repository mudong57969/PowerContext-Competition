# 数字集成电路 讲义

本讲义覆盖数字集成电路（digital integrated circuit）与 VLSI 设计基础，包含 MOS 器件、CMOS 反相器（inverter）、功耗、互连线与工艺缩放五个章节。

## 第一章 MOS 器件

### MOS 阈值电压
MOS 晶体管的阈值电压 VTH（threshold voltage）由栅氧化层厚度与衬底掺杂浓度决定。体效应会使阈值电压绝对值增大。

### MOS 工作区
NMOS 饱和区条件为 VGS ≥ VT 且 VDS ≥ VGS − VT；线性区（linear region）条件为 VDS < VGS − VT；截止区（cutoff）条件为 VGS < VT。

### 体效应
源衬电压 VSB 增大时耗尽层电荷增多，阈值电压随之升高，这一现象称为体效应（body effect）。衬底偏置越大，阈值电压漂移越大。

### 沟道长度调制
饱和区漏极电压继续增大使有效沟道长度缩短，漏电流随 VDS 缓慢上升，即沟道长度调制（channel length modulation），可用厄尔利电压 λ 描述。

## 第二章 CMOS 反相器

### CMOS VTC 与噪声容限
CMOS 反相器过渡区内两管同时饱和导通，VTC 最陡。高电平噪声容限 NMH = VOH − VIH，低电平噪声容限 NML = VIL − VOL。噪声容限（noise margin）越大，抗干扰能力越强。

### 传播延迟
传播延迟 tp（propagation delay）定义为输入 50% 到输出 50% 的时间，常取 tPHL 与 tPLH 的平均值。增大宽长比或减小负载电容可以减小延迟。

## 第三章 功耗

### 动态功耗
动态功耗（dynamic power）P = α·CL·VDD²·f，其中 α 是开关活动因子（switching activity），CL 是负载电容，f 是工作频率。

### 短路功耗
输入跳变时 NMOS 与 PMOS 短暂同时导通，电源到地形成直流通路，产生短路功耗（short-circuit power）。

### 泄漏功耗
阈值电压降低时亚阈值泄漏电流（subthreshold leakage）指数增大。泄漏功耗（leakage power）即静态功耗，在低阈值电压工艺中占比显著。

## 第四章 互连线

### 互连延迟
工艺缩小后互连线 RC delay（interconnect delay）占比上升，可用 Elmore 延迟模型估算分布式 RC 网络的延迟。

### 扇出与扇入
扇出（fan-out）是一个门驱动同类门的数目，扇入（fan-in）是门的输入数。扇出增大时负载电容增大，门延迟增大。

## 第五章 工艺与缩放

### 尺寸缩放与功耗密度
尺寸缩放（scaling）按比例缩小晶体管尺寸可提高集成度与速度，但 Dennard 缩放失效后，功耗密度（power density）随工艺进步上升，成为主要瓶颈。
