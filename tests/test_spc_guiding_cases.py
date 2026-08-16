from datetime import date

import pytest

from lexora_ai.application.case_law_sync import (
    CaseLawSourceLocator,
    parse_case_law_manifest,
)
from lexora_ai.infrastructure.spc_guiding_cases import (
    SpcGuidingCaseConnector,
    SpcGuidingCaseError,
)


def test_parser_extracts_structured_official_guiding_case() -> None:
    html = """
    <div class="detail">
      <div class="title">指导案例240号：某公司诉某配送员劳动争议案</div>
      <div class="clearfix detail_mes">
        <li>来源：最高人民法院</li><li>发布时间：2024-05-23 10:00:00</li>
      </div>
      <div class="txt big"><div class="txt_txt">
        <p><strong>指导案例240号</strong></p>
        <p><strong>关键词　民事　平台用工　劳动关系</strong></p>
        <p><strong>裁判要点</strong></p><p>应当根据用工事实判断劳动关系。</p>
        <p><strong>相关法条</strong></p><p>劳动合同法第七条</p>
        <p><strong>基本案情</strong></p><p>配送员接受平台管理。</p>
        <p><strong>裁判结果</strong></p><p>确认存在劳动关系。</p>
        <p><strong>裁判理由</strong></p><p>平台实施了劳动管理。</p>
      </div></div>
    </div>
    """

    source = SpcGuidingCaseConnector().parse(
        "https://www.court.gov.cn/shenpan/xiangqing/450751.html",
        html,
    )

    assert source.case_number == "指导案例240号"
    assert source.title == "某公司诉某配送员劳动争议案"
    assert source.keywords == ["民事", "平台用工", "劳动关系"]
    assert source.published_on == date(2024, 5, 23)
    assert "裁判要点\n应当根据用工事实判断劳动关系。" in source.content


def test_connector_rejects_non_official_hosts_before_download() -> None:
    with pytest.raises(SpcGuidingCaseError, match="court.gov.cn"):
        SpcGuidingCaseConnector().parse("https://example.com/case", "<html></html>")


def test_parser_extracts_structured_official_reference_case() -> None:
    html = """
    <div class="detail">
      <div class="title">入库参考案例：徐某盗窃案</div>
      <div class="clearfix detail_mes">
        <li>来源：人民法院报</li><li>发布时间：2025-01-09 08:54:07</li>
      </div>
      <div class="txt big"><div class="txt_txt">
        <p>徐某盗窃案</p>
        <p>入库编号2024-18-1-221-001</p>
        <p>关键词 刑事 盗窃罪 量刑均衡</p>
        <p>基本案情</p><p>徐某多次盗窃他人财物。</p>
        <p>裁判理由</p><p>应当坚持罪责刑相适应。</p>
        <p>裁判要旨</p><p>量刑应当综合全案情节。</p>
        <p>关联索引</p><p>《中华人民共和国刑法》第264条</p>
      </div></div>
    </div>
    """

    source = SpcGuidingCaseConnector().parse(
        "https://www.court.gov.cn/zixun/xiangqing/452231.html",
        html,
    )

    assert source.case_number == "入库编号 2024-18-1-221-001"
    assert source.title == "徐某盗窃案"
    assert source.keywords == ["刑事", "盗窃罪", "量刑均衡"]
    assert source.source_name == "人民法院案例库入库参考案例"
    assert source.published_on == date(2025, 1, 9)
    assert "裁判要旨\n量刑应当综合全案情节。" in source.content


def test_parser_selects_cases_from_one_official_typical_case_collection() -> None:
    html = """
    <div class="detail">
      <div class="title">涉婚姻家庭纠纷典型案例</div>
      <div class="clearfix detail_mes">
        <li>来源：最高人民法院新闻局</li>
        <li>发布时间：2025-01-15 19:55:26</li>
      </div>
      <div class="txt big"><div class="txt_txt">
        <p>案例一：婚前房产加名——崔某某与陈某某离婚纠纷案</p>
        <p>案例二：父母出资购房——范某某与许某某离婚纠纷案</p>
        <p>案例三：藏匿子女——颜某某申请人格权侵害禁令案</p>
        <p>案例四：赠与第三人——崔某某与叶某某及高某某赠与合同纠纷案</p>
        <p>案例一：婚前房产加名——崔某某与陈某某离婚纠纷案</p>
        <p>〖基本案情〗</p><p>婚后将婚前房屋登记为双方共有。</p>
        <p>〖裁判结果〗</p><p>房屋归给予方并补偿另一方。</p>
        <p>〖典型意义〗</p><p>综合共同生活和家庭贡献合理补偿。</p>
        <p>案例二：父母出资购房——范某某与许某某离婚纠纷案</p>
        <p>〖基本案情〗</p><p>一方父母全款购房并登记至双方名下。</p>
        <p>〖裁判结果〗</p><p>房屋归出资方子女并补偿另一方。</p>
        <p>〖典型意义〗</p><p>综合出资来源与婚姻存续时间。</p>
        <p>案例三：藏匿子女——颜某某申请人格权侵害禁令案</p>
        <p>〖基本案情〗</p><p>一方藏匿子女。</p>
        <p>〖裁判结果〗</p><p>法院签发禁令。</p>
        <p>〖典型意义〗</p><p>及时保护未成年人。</p>
        <p>案例四：赠与第三人——崔某某与叶某某及高某某赠与合同纠纷案</p>
        <p>〖基本案情〗</p><p>一方擅自向第三人转账。</p>
        <p>〖裁判结果〗</p><p>赠与无效并全部返还。</p>
        <p>〖典型意义〗</p><p>维护夫妻共同财产平等处理权。</p>
        <p>责任编辑：某某</p>
      </div></div>
    </div>
    """

    sources = SpcGuidingCaseConnector().parse_many(
        CaseLawSourceLocator(
            source_url="https://www.court.gov.cn/zixun/xiangqing/452761.html",
            case_ordinals=(1, 2, 4),
        ),
        html,
    )

    assert [source.case_number for source in sources] == [
        "最高法典型案例 2025-01-15 案例一",
        "最高法典型案例 2025-01-15 案例二",
        "最高法典型案例 2025-01-15 案例四",
    ]
    assert [source.title for source in sources] == [
        "崔某某与陈某某离婚纠纷案",
        "范某某与许某某离婚纠纷案",
        "崔某某与叶某某及高某某赠与合同纠纷案",
    ]
    assert all(source.source_name == "最高人民法院典型案例" for source in sources)
    assert "典型意义\n维护夫妻共同财产平等处理权。" in sources[2].content
    assert "责任编辑" not in sources[2].content


def test_parser_handles_case_title_before_typical_summary() -> None:
    html = """
    <div class="detail">
      <div class="title">反家庭暴力犯罪典型案例</div>
      <div class="clearfix detail_mes"><li>发布时间：2024-11-25 10:00:13</li></div>
      <div class="txt big"><div class="txt_txt">
        <p>案例四</p>
        <p>被告人刘某坤虐待、重婚案——依法惩处</p>
        <p>〖基本案情〗</p><p>已有配偶又与他人以夫妻名义共同生活。</p>
        <p>〖裁判结果〗</p><p>以重婚罪判处有期徒刑一年。</p>
        <p>〖典型意义〗</p><p>保护共同生活的妇女和未成年人。</p>
      </div></div>
    </div>
    """

    source = SpcGuidingCaseConnector().parse_many(
        CaseLawSourceLocator(
            source_url="https://www.court.gov.cn/zixun/xiangqing/448541.html",
            case_ordinals=(4,),
        ),
        html,
    )[0]

    assert source.title == "被告人刘某坤虐待、重婚案"
    assert source.case_number == "最高法典型案例 2024-11-25 案例四"


def test_manifest_accepts_individual_pages_and_selected_collection_cases() -> None:
    locators = parse_case_law_manifest(
        [
            "https://www.court.gov.cn/shenpan/xiangqing/27821.html",
            {
                "url": "https://www.court.gov.cn/zixun/xiangqing/452761.html",
                "case_ordinals": [1, 2, 4],
            },
        ]
    )

    assert locators == [
        CaseLawSourceLocator(
            source_url="https://www.court.gov.cn/shenpan/xiangqing/27821.html"
        ),
        CaseLawSourceLocator(
            source_url="https://www.court.gov.cn/zixun/xiangqing/452761.html",
            case_ordinals=(1, 2, 4),
        ),
    ]


def test_parser_rejects_missing_selected_collection_case() -> None:
    html = """
    <div class="detail">
      <div class="title">典型案例</div>
      <div class="clearfix detail_mes"><li>发布时间：2025-01-15 19:55:26</li></div>
      <div class="txt big"><div class="txt_txt">
        <p>案例一：某离婚纠纷案</p>
        <p>〖基本案情〗</p><p>事实。</p>
        <p>〖裁判结果〗</p><p>结果。</p>
        <p>〖典型意义〗</p><p>意义。</p>
      </div></div>
    </div>
    """

    with pytest.raises(SpcGuidingCaseError, match="not found: 2"):
        SpcGuidingCaseConnector().parse_many(
            CaseLawSourceLocator(
                source_url="https://www.court.gov.cn/zixun/xiangqing/452761.html",
                case_ordinals=(2,),
            ),
            html,
        )
