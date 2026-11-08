"""Built-in sample question bank for the 数字集成电路 course.

24 hand-written questions across 12 knowledge points, authored for this
project (no external copyright content). Each question carries an answer and
a short explanation so grading and the mistake book are fully deterministic.

The bank is installed once per (session, course) pair on demand; chapters and
knowledge points are created if they do not exist yet.
"""

from __future__ import annotations

import json

from app.core.seekdb import get_engine
from app.services.documents import get_or_create_chapter, get_or_create_kp

SAMPLE_COURSE = "数字集成电路"

SAMPLE_CHAPTERS = ["MOS 器件", "CMOS 反相器", "功耗", "互连线", "工艺与缩放"]

SAMPLE_KNOWLEDGE_POINTS: list[tuple[str, str]] = [
    ("MOS 阈值电压", "MOS 器件"),
    ("MOS 工作区", "MOS 器件"),
    ("体效应", "MOS 器件"),
    ("沟道长度调制", "MOS 器件"),
    ("CMOS VTC 与噪声容限", "CMOS 反相器"),
    ("传播延迟", "CMOS 反相器"),
    ("动态功耗", "功耗"),
    ("短路功耗", "功耗"),
    ("泄漏功耗", "功耗"),
    ("互连延迟", "互连线"),
    ("扇出与扇入", "互连线"),
    ("尺寸缩放与功耗密度", "工艺与缩放"),
]

SAMPLE_QUESTIONS: list[dict] = [
    {
        "type": "single_choice",
        "knowledge_point": "MOS 阈值电压",
        "chapter": "MOS 器件",
        "difficulty": 2,
        "stem": "MOS 晶体管的阈值电压 VT 主要取决于下列哪一项？",
        "options": ["沟道长度", "栅氧化层厚度与衬底掺杂浓度", "漏极电压", "工作频率"],
        "answer": "B",
        "explanation": "阈值电压由栅氧化层电容、功函数差、衬底掺杂浓度等工艺参数决定，与沟道长度、漏极电压和工作频率没有直接关系。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "MOS 工作区",
        "chapter": "MOS 器件",
        "difficulty": 2,
        "stem": "NMOS 满足 VGS > VT 且 VDS < VGS − VT 时，工作在哪个区？",
        "options": ["截止区", "线性区（三极管区）", "饱和区", "击穿区"],
        "answer": "B",
        "explanation": "导通且漏源压降小于过驱动电压时，沟道尚未在漏端夹断，器件工作在线性区，电流近似与 VDS 成正比。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "MOS 工作区",
        "chapter": "MOS 器件",
        "difficulty": 2,
        "stem": "NMOS 处于饱和区的电压条件是下列哪一项？",
        "options": [
            "VGS < VT",
            "VDS < VGS − VT",
            "VGS ≥ VT 且 VDS ≥ VGS − VT",
            "VDS > VDD",
        ],
        "answer": "C",
        "explanation": "饱和区要求沟道导通且漏端夹断：VGS ≥ VT 且 VDS ≥ VGS − VT，此时电流近似与 VDS 无关（忽略沟道长度调制）。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "体效应",
        "chapter": "MOS 器件",
        "difficulty": 2,
        "stem": "源极与衬底之间存在反偏电压时，体效应（衬偏效应）会使阈值电压发生什么变化？",
        "options": ["绝对值增大", "绝对值减小", "保持不变", "先增大后减小"],
        "answer": "A",
        "explanation": "源衬反偏使耗尽层展宽，需要更大的栅压才能形成沟道，因此阈值电压的绝对值增大。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "沟道长度调制",
        "chapter": "MOS 器件",
        "difficulty": 2,
        "stem": "考虑沟道长度调制效应后，饱和区漏电流随 VDS 增大如何变化？",
        "options": ["略有增大", "明显减小", "保持不变", "降为零"],
        "answer": "A",
        "explanation": "有效沟道长度随 VDS 增大而缩短，使饱和电流随 VDS 略有增大，等效为一个有限的输出电阻。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "CMOS VTC 与噪声容限",
        "chapter": "CMOS 反相器",
        "difficulty": 2,
        "stem": "CMOS 反相器输入电压在 VDD/2 附近（过渡区）时，NMOS 与 PMOS 处于什么状态？",
        "options": [
            "两个都截止",
            "两个都导通且处于饱和区",
            "一个饱和一个截止",
            "两个都处于线性区",
        ],
        "answer": "B",
        "explanation": "过渡区内两管同时导通且均处于饱和区，输出阻抗最小、增益最大，VTC 在此处最陡峭。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "CMOS VTC 与噪声容限",
        "chapter": "CMOS 反相器",
        "difficulty": 1,
        "stem": "高电平噪声容限 NMH 的表达式是下列哪一项？",
        "options": ["VOH − VIH", "VIL − VOL", "VIH − VIL", "VDD − VT"],
        "answer": "A",
        "explanation": "NMH = VOH(min) − VIH(min)，NML = VIL(max) − VOL(max)，分别衡量高、低电平可容忍的噪声幅度。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "传播延迟",
        "chapter": "CMOS 反相器",
        "difficulty": 2,
        "stem": "下列哪种方法最直接地减小反相器的传播延迟？",
        "options": [
            "降低电源电压",
            "增大晶体管宽长比或减小负载电容",
            "增加互连长度",
            "降低时钟频率",
        ],
        "answer": "B",
        "explanation": "传播延迟近似正比于负载电容与等效电阻的乘积；增大宽长比降低等效电阻、减小负载电容都能直接减小延迟。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "动态功耗",
        "chapter": "功耗",
        "difficulty": 2,
        "stem": "动态功耗公式 P = α·CL·VDD²·f 中，α 表示什么？",
        "options": ["开关活动因子", "载流子迁移率", "阈值电压", "温度系数"],
        "answer": "A",
        "explanation": "α 是每个时钟周期内节点发生 0→1 翻转的平均概率，反映电路的实际开关活动情况。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "泄漏功耗",
        "chapter": "功耗",
        "difficulty": 2,
        "stem": "阈值电压降低时，亚阈值泄漏电流如何变化？",
        "options": ["指数增大", "线性增大", "保持不变", "线性减小"],
        "answer": "A",
        "explanation": "亚阈值电流与 exp((VGS − VT)/(n·VT_thermal)) 成正比，VT 降低使泄漏电流指数级增大。",
    },
    {
        "type": "single_choice",
        "knowledge_point": "扇出与扇入",
        "chapter": "互连线",
        "difficulty": 2,
        "stem": "某逻辑门的扇出（fan-out）增大时，其输出延迟通常会如何变化？",
        "options": ["增大", "减小", "保持不变", "先减小后增大"],
        "answer": "A",
        "explanation": "扇出增大意味着负载电容增大，输出等效 RC 时间常数变大，因此延迟增加。",
    },
    {
        "type": "multi_choice",
        "knowledge_point": "动态功耗",
        "chapter": "功耗",
        "difficulty": 2,
        "stem": "下列哪些措施可以有效降低动态功耗？（多选）",
        "options": [
            "降低电源电压 VDD",
            "减小负载电容 CL",
            "降低开关活动因子 α",
            "提高时钟频率 f",
        ],
        "answer": "ABC",
        "explanation": "动态功耗与 VDD²、CL、α、f 成正比，前三项降低均可减小动态功耗；提高频率反而增大功耗。",
    },
    {
        "type": "multi_choice",
        "knowledge_point": "传播延迟",
        "chapter": "CMOS 反相器",
        "difficulty": 2,
        "stem": "下列哪些因素会影响 CMOS 反相器的传播延迟？（多选）",
        "options": ["负载电容", "电源电压", "晶体管尺寸（宽长比）", "衬底颜色"],
        "answer": "ABC",
        "explanation": "延迟由等效电阻与负载电容的乘积决定，电源电压影响过驱动、尺寸影响等效电阻；衬底颜色与电学特性无关。",
    },
    {
        "type": "multi_choice",
        "knowledge_point": "泄漏功耗",
        "chapter": "功耗",
        "difficulty": 3,
        "stem": "静态 CMOS 电路泄漏功耗的主要来源包括哪些？（多选）",
        "options": [
            "亚阈值泄漏电流",
            "栅极隧穿电流",
            "源漏结反偏泄漏电流",
            "动态开关电流",
        ],
        "answer": "ABC",
        "explanation": "泄漏功耗来自器件关断时仍存在的亚阈值、栅极隧穿和结反偏电流；动态开关电流属于动态功耗。",
    },
    {
        "type": "multi_choice",
        "knowledge_point": "MOS 工作区",
        "chapter": "MOS 器件",
        "difficulty": 1,
        "stem": "MOS 晶体管的三个基本工作区是哪些？（多选）",
        "options": ["截止区", "线性区", "饱和区", "雪崩区"],
        "answer": "ABC",
        "explanation": "数字电路中的 MOS 管主要工作在截止区（关断）与线性区/饱和区（导通）；雪崩击穿属于异常工作状态。",
    },
    {
        "type": "true_false",
        "knowledge_point": "短路功耗",
        "chapter": "功耗",
        "difficulty": 1,
        "stem": "输入信号跳变期间，CMOS 反相器中的 NMOS 与 PMOS 会短暂同时导通，从而产生短路功耗。",
        "answer": "对",
        "explanation": "跳变期间两管同时导通，VDD 到地形成直流通路，产生短路电流，对应的功耗称为短路（直通）功耗。",
    },
    {
        "type": "true_false",
        "knowledge_point": "动态功耗",
        "chapter": "功耗",
        "difficulty": 1,
        "stem": "静态 CMOS 电路在输出保持不变时，理想情况下动态功耗为零。",
        "answer": "对",
        "explanation": "动态功耗来源于节点充放电，仅在发生 0→1 翻转时消耗；输出保持时只有泄漏功耗。",
    },
    {
        "type": "true_false",
        "knowledge_point": "互连延迟",
        "chapter": "互连线",
        "difficulty": 3,
        "stem": "随着工艺尺寸不断缩小，互连线延迟在关键路径延迟中所占的比重整体呈下降趋势。",
        "answer": "错",
        "explanation": "尺寸缩小使门延迟下降，但导线电阻增大、间距减小使互连 RC 延迟恶化，互连延迟占比反而上升。",
    },
    {
        "type": "true_false",
        "knowledge_point": "体效应",
        "chapter": "MOS 器件",
        "difficulty": 2,
        "stem": "源极与衬底之间的反偏电压越大，MOS 晶体管阈值电压的绝对值越小。",
        "answer": "错",
        "explanation": "源衬反偏使耗尽层展宽、表面势垒提高，阈值电压绝对值增大而非减小。",
    },
    {
        "type": "true_false",
        "knowledge_point": "CMOS VTC 与噪声容限",
        "chapter": "CMOS 反相器",
        "difficulty": 3,
        "stem": "提高电源电压 VDD 通常会同时增大噪声容限和动态功耗。",
        "answer": "对",
        "explanation": "VDD 增大使 VOH−VOL 摆幅增大，噪声容限随之提高；但动态功耗与 VDD² 成正比，功耗也显著增大。",
    },
    {
        "type": "short_answer",
        "knowledge_point": "动态功耗",
        "chapter": "功耗",
        "difficulty": 2,
        "stem": "写出 CMOS 电路动态功耗的计算公式，并说明每个符号的含义。",
        "answer": "P = α·CL·VDD²·f；α 为开关活动因子，CL 为负载电容，VDD 为电源电压，f 为时钟频率",
        "explanation": "动态功耗由节点充放电引起，与活动因子、负载电容、电压平方和频率成正比；电压是最有效的调节手段。",
    },
    {
        "type": "short_answer",
        "knowledge_point": "MOS 工作区",
        "chapter": "MOS 器件",
        "difficulty": 2,
        "stem": "写出 NMOS 处于饱和区的电压条件。",
        "answer": "VGS ≥ VT 且 VDS ≥ VGS − VT（沟道导通且漏端夹断）",
        "explanation": "饱和区要求器件导通（VGS ≥ VT）且漏端夹断（VDS ≥ VGS − VT），此时电流近似恒定。",
    },
    {
        "type": "short_answer",
        "knowledge_point": "传播延迟",
        "chapter": "CMOS 反相器",
        "difficulty": 1,
        "stem": "反相器传播延迟 tp 是如何定义的？",
        "answer": "输入波形跳变 50% 点到输出波形跳变 50% 点之间的时间，通常取 tpHL 与 tpLH 的平均值",
        "explanation": "tpHL 为输出由高到低的延迟，tpLH 为输出由低到高的延迟，两者平均即为传播延迟 tp。",
    },
    {
        "type": "short_answer",
        "knowledge_point": "尺寸缩放与功耗密度",
        "chapter": "工艺与缩放",
        "difficulty": 3,
        "stem": "恒定电场（constant-field）缩放中，电源电压与器件尺寸如何变化？",
        "answer": "电源电压与所有尺寸按同一比例缩小，使内部电场保持不变",
        "explanation": "恒定电场缩放将电压、沟道长度、氧化层厚度等按同一因子缩小，保证电场强度不变，从而避免可靠性问题。",
    },
    {
        "type": "short_answer",
        "knowledge_point": "泄漏功耗",
        "chapter": "功耗",
        "difficulty": 2,
        "stem": "列举降低亚阈值泄漏电流的两种常用技术。",
        "answer": "提高阈值电压（如多阈值/高VT器件）、电源门控（power gating）、体偏置、降低工作温度等（答出任意两种即可）",
        "explanation": "亚阈值电流随 VT 指数衰减，高 VT 器件、电源门控、反向体偏置与降温均能有效抑制泄漏。",
    },
]


def ensure_question_bank(session_id: str, course_id: int) -> int:
    """Install the sample bank once per (session, course). Returns inserted count."""
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM questions WHERE session_id=%s AND course_id=%s AND is_generated=0",
            (session_id, course_id),
        )
        if cur.fetchone()[0] > 0:
            return 0
        chapter_map = {
            name: get_or_create_chapter(cur, course_id, name)
            for name in SAMPLE_CHAPTERS
        }
        kp_map = {
            name: get_or_create_kp(cur, course_id, chapter_map.get(chapter), name)
            for name, chapter in SAMPLE_KNOWLEDGE_POINTS
        }
        inserted = 0
        for q in SAMPLE_QUESTIONS:
            kp_id = kp_map.get(q["knowledge_point"])
            chapter_id = chapter_map.get(q.get("chapter") or "")
            if kp_id is None:
                continue
            cur.execute(
                "INSERT INTO questions (session_id, course_id, chapter_id, question_type, "
                "stem, options, answer, explanation, difficulty, is_generated, review_status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0, 'approved')",
                (
                    session_id,
                    course_id,
                    chapter_id,
                    q["type"],
                    q["stem"],
                    json.dumps(q["options"], ensure_ascii=False)
                    if q.get("options")
                    else None,
                    q["answer"],
                    q["explanation"],
                    q["difficulty"],
                ),
            )
            question_id = int(cur.lastrowid)
            cur.execute(
                "INSERT INTO question_knowledge_links (question_id, knowledge_point_id) "
                "VALUES (%s, %s)",
                (question_id, kp_id),
            )
            inserted += 1
    return inserted


def question_count(session_id: str, course_id: int) -> int:
    eng = get_engine()
    with eng.connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM questions WHERE session_id=%s AND course_id=%s",
            (session_id, course_id),
        )
        return int(cur.fetchone()[0])
