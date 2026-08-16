from datetime import date

import pytest

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
