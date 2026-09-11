"""生成中文演示卷宗 PDF 并按目录入库（可重复执行，会清空重建演示案件）。

用法: backend/.venv/bin/python seed_demo.py
依赖: reportlab（使用内置 CID 字体 STSong-Light，无需外部中文字体文件）
"""
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from app.config import STORAGE_DIR
from app.db import DEFAULT_FOLDERS, init_pool, init_schema, pool
from app.pdf_service import save_pdf_then_index

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

H1 = ParagraphStyle("H1", fontName="STSong-Light", fontSize=18, leading=28,
                    alignment=1, spaceAfter=14)
H2 = ParagraphStyle("H2", fontName="STSong-Light", fontSize=13, leading=22,
                    spaceBefore=10, spaceAfter=6)
BODY = ParagraphStyle("BODY", fontName="STSong-Light", fontSize=11.5,
                      leading=22, firstLineIndent=23)
PLAIN = ParagraphStyle("PLAIN", fontName="STSong-Light", fontSize=11.5, leading=22)


def build_pdf(blocks: list[tuple[str, str]]) -> bytes:
    """blocks: (style, text) — style ∈ title/h2/body/plain/pagebreak/spacer"""
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=56, bottomMargin=46,
                            leftMargin=54, rightMargin=54, title="卷宗")
    story: list = []
    styles = {"title": H1, "h2": H2, "body": BODY, "plain": PLAIN}
    for kind, text in blocks:
        if kind == "pagebreak":
            story.append(PageBreak())
            continue
        if kind == "spacer":
            story.append(Spacer(1, float(text)))
            continue
        for para in text.split("\n"):
            story.append(Paragraph(para, styles[kind]))
    doc.build(story)
    return buf.getvalue()


# ---------------------------- 各份卷宗内容 ----------------------------

QISU = [
    ("title", "民事起诉状"),
    ("plain", "原告：张伟，男，汉族，1978年5月12日出生，住北京市朝阳区建国路88号。"),
    ("plain", "被告：李伟，男，汉族，1980年9月3日出生，住北京市海淀区中关村南大街15号。"),
    ("h2", "诉讼请求"),
    ("body", "一、请求判令解除原告与被告于2023年3月1日签订的《房屋租赁合同》；"),
    ("body", "二、请求判令被告支付拖欠租金人民币壹拾贰万陆仟元（计算至2026年6月30日）；"),
    ("body", "三、请求判令被告支付违约金人民币叁万柒仟捌佰元；"),
    ("body", "四、本案诉讼费用由被告承担。"),
    ("h2", "事实与理由"),
    ("body", "2023年3月1日，原告张伟与被告李伟签订《房屋租赁合同》，"
             "约定原告将位于朝阳区建国路88号的办公用房出租给被告，"
             "月租金人民币贰万壹仟元，按月支付，租期五年。"),
    ("body", "自2025年10月起，被告以经营困难为由开始拖欠租金，"
             "经原告多次书面催告仍拒不支付。截至2026年6月30日，"
             "被告累计拖欠租金达六个月，共计人民币壹拾贰万陆仟元。"),
    ("body", "根据合同第十二条约定，承租方逾期支付租金超过三十日的，"
             "出租方有权解除合同并要求承租方支付相当于两个月租金的违约金。"
             "依据《中华人民共和国民法典》第五百六十三条、第七百二十二条之规定，"
             "特向贵院提起诉讼，恳请依法判决。"),
    ("spacer", "20"),
    ("plain", "此致  北京市朝阳区人民法院"),
    ("spacer", "24"),
    ("plain", "具状人：张伟        2026年7月5日"),
]

ZHENGJU = [
    ("title", "证据目录"),
    ("h2", "证据一：《房屋租赁合同》"),
    ("body", "证明目的：证明原、被告之间存在房屋租赁合同关系，"
             "双方对租金标准、支付方式及违约责任作出明确约定。"),
    ("h2", "证据二：房屋产权证书"),
    ("body", "证明目的：证明原告张伟系涉案出租房屋的合法所有权人。"),
    ("h2", "证据三：租金催告函及快递签收记录"),
    ("body", "证明目的：证明原告于2026年1月、3月、5月三次书面向被告催告拖欠租金，"
             "被告均已签收但拒不履行付款义务。"),
    ("h2", "证据四：银行流水"),
    ("body", "证明目的：证明被告自2025年10月起未再支付租金，"
             "历史租金支付标准为每月人民币贰万壹仟元。"),
    ("h2", "证据五：微信聊天记录公证书"),
    ("body", "证明目的：证明被告承认拖欠租金事实并多次承诺还款但均未兑现。"),
]

DAILI = [
    ("title", "代理词"),
    ("body", "审判长、审判员：北京市正义律师事务所接受原告张伟的委托，"
             "指派王律师担任其诉讼代理人。结合庭审情况，发表如下代理意见："),
    ("body", "第一，本案房屋租赁合同合法有效，双方均应严格履行。"
             "被告承租房屋后长期拖欠租金，构成根本违约。"),
    ("body", "第二，合同约定的解除条件已经成就。"
             "被告逾期支付租金已远超三十日，原告依法享有合同解除权。"),
    ("body", "第三，原告主张的租金及违约金计算方式清楚、依据充分，应予全额支持。"
             "以上意见，请合议庭予以采纳。"),
    ("spacer", "24"),
    ("plain", "代理人：王律师    北京市正义律师事务所    2026年8月20日"),
]

PANJUE = [
    ("title", "北京市朝阳区人民法院民事判决书"),
    ("plain", "(2026)京0105民初1234号"),
    ("body", "原告张伟与被告李伟房屋租赁合同纠纷一案，本院于2026年7月15日立案后，"
             "依法适用简易程序公开开庭进行了审理。原告委托诉讼代理人王律师，"
             "被告李伟到庭参加诉讼。本案现已审理终结。"),
    ("body", "经审理查明：2023年3月1日原、被告签订《房屋租赁合同》，"
             "约定月租金贰万壹仟元，租期五年。被告自2025年10月起未付租金，"
             "截至2026年6月30日累计拖欠六个月租金共计壹拾贰万陆仟元。"
             "原告三次书面催告，被告均未履行。"),
    ("body", "本院认为：涉案合同合法有效，被告逾期支付租金超过三十日，"
             "合同约定的解除条件已成就。判决如下："),
    ("body", "一、解除原告张伟与被告李伟签订的《房屋租赁合同》；"),
    ("body", "二、被告李伟于本判决生效之日起十日内向原告张伟支付"
             "拖欠租金壹拾贰万陆仟元；"),
    ("body", "三、被告李伟向原告张伟支付违约金叁万柒仟捌佰元；"),
    ("body", "案件受理费由被告李伟负担。如不服本判决，可在判决书送达之日起"
             "十五日内上诉于北京市第三中级人民法院。"),
    ("spacer", "24"),
    ("plain", "审判员：刘某某        二〇二六年九月二日"),
]

HETONG = [
    ("title", "工矿产品买卖合同"),
    ("plain", "合同编号：CG-2024-1107"),
    ("plain", "出卖人：华信机械设备制造有限公司"),
    ("plain", "买受人：恒远建设工程有限公司"),
    ("h2", "第一条 标的物"),
    ("body", "出卖人向买受人供应塔式起重机两台及配套标准节四十节，"
             "型号规格详见合同附件一，总价款人民币壹佰捌拾陆万元整。"),
    ("h2", "第二条 交付与验收"),
    ("body", "出卖人应于2024年12月31日前将货物运抵买受人位于通州区的施工现场，"
             "运费由出卖人承担。买受人应在到货后七日内组织验收并签署验收单。"),
    ("h2", "第三条 付款方式"),
    ("body", "合同签订后三日内买受人支付预付款30%，即人民币伍拾伍万捌仟元；"
             "验收合格后三十日内支付剩余货款70%，即人民币壹佰叁拾万贰仟元。"),
    ("h2", "第四条 质量保证与第五条 违约责任"),
    ("body", "质量保证期为验收合格之日起十二个月，质保期内出现质量问题的，"
             "出卖人应在四十八小时内到场维修或更换。"
             "买受人逾期付款的，每逾期一日按应付未付金额的万分之五支付违约金。"),
]

CUIKUAN = [
    ("title", "催款函"),
    ("plain", "致：恒远建设工程有限公司"),
    ("body", "贵我双方于2024年11月7日签订《工矿产品买卖合同》。"
             "我司已按约于2024年12月20日交付全部塔式起重机及配件，"
             "贵司验收合格并签署验收单。"),
    ("body", "按照合同约定，贵司应于2025年1月24日前付清全部货款。"
             "截至本函发出之日，贵司仅支付预付款及到货款共计玖拾万元，"
             "尚欠货款人民币玖拾陆万元整，逾期已超过一年。"),
    ("body", "我司郑重催告：请贵司于收到本函之日起十五日内付清所欠货款"
             "及相应违约金。逾期仍不支付的，我司将依法提起诉讼并申请财产保全，"
             "届时产生的诉讼费、保全费、律师费等均由贵司承担。"),
    ("spacer", "24"),
    ("plain", "华信机械设备制造有限公司        2026年3月10日"),
]

# 案件 -> (基本信息, 额外自定义目录, [(文件名, 目录名, 内容块)])
CASES = [
    {
        "case_no": "(2026)京0105民初1234号",
        "title": "张伟诉李伟房屋租赁合同纠纷案",
        "cause": "房屋租赁合同纠纷",
        "parties": "原告：张伟\n被告：李伟",
        "lawyer": "王律师",
        "remark": "办公用房拖欠租金六个月，已判决解除合同",
        "extra_folders": [],
        "docs": [
            ("民事起诉状.pdf", "诉讼文书", QISU),
            ("代理词.pdf", "诉讼文书", DAILI),
            ("证据目录.pdf", "证据材料", ZHENGJU),
            ("民事判决书.pdf", "裁判文书", PANJUE),
        ],
    },
    {
        "case_no": "(2026)京0112民初5678号",
        "title": "华信机械公司诉恒远建设公司买卖合同纠纷案",
        "cause": "买卖合同纠纷",
        "parties": "原告：华信机械设备制造有限公司\n被告：恒远建设工程有限公司",
        "lawyer": "陈律师",
        "remark": "塔式起重机货款拖欠，已发催款函",
        "extra_folders": ["合同文件", "往来函件"],
        "docs": [
            ("工矿产品买卖合同.pdf", "合同文件", HETONG),
            ("催款函.pdf", "往来函件", CUIKUAN),
        ],
    },
]


def reset_and_seed() -> None:
    init_pool()
    init_schema()
    with pool.connection() as conn:
        conn.execute("TRUNCATE cases RESTART IDENTITY CASCADE")
        conn.commit()
    for f in STORAGE_DIR.rglob("*.pdf"):
        f.unlink()

    out_dir = Path("/tmp/demo-pdfs")
    out_dir.mkdir(exist_ok=True)

    for case in CASES:
        with pool.connection() as conn:
            crow = conn.execute(
                """
                INSERT INTO cases (case_no, title, cause, parties, lawyer, remark)
                VALUES (%(case_no)s, %(title)s, %(cause)s, %(parties)s,
                        %(lawyer)s, %(remark)s)
                RETURNING id
                """,
                case,
            ).fetchone()
            conn.commit()
            case_id = crow[0]

            # 默认目录 + 自定义目录
            folder_names = DEFAULT_FOLDERS + case["extra_folders"]
            for pos, name in enumerate(folder_names):
                conn.execute(
                    "INSERT INTO folders (case_id, name, position) VALUES (%s,%s,%s)",
                    (case_id, name, pos),
                )
            name_to_id = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT name, id FROM folders WHERE case_id=%s", (case_id,)
                ).fetchall()
            }
            conn.commit()

        for filename, folder_name, blocks in case["docs"]:
            pdf = build_pdf(blocks)
            (out_dir / filename).write_bytes(pdf)
            with pool.connection() as conn:
                drow = conn.execute(
                    """
                    INSERT INTO documents (case_id, folder_id, filename, stored_name,
                                           size_bytes, status)
                    VALUES (%s, %s, %s, '', %s, 'processing')
                    RETURNING id
                    """,
                    (case_id, name_to_id[folder_name], filename, len(pdf)),
                ).fetchone()
                conn.commit()
                doc_id = drow[0]
            save_pdf_then_index(doc_id, filename, pdf)
            print(f"  案件#{case_id} [{folder_name}] 《{filename}》"
                  f"({len(pdf)//1024}KB)")

    print("演示数据就绪。")


if __name__ == "__main__":
    reset_and_seed()
