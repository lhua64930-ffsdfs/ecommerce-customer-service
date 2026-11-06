"""PII 脱敏规则单测。"""
from app.utils.pii import mask_address, mask_name, mask_phone


def test_mask_phone_keeps_prefix_and_suffix() -> None:
    assert mask_phone("13800006789") == "138****6789"


def test_mask_phone_handles_empty_and_short_values() -> None:
    assert mask_phone(None) == ""
    assert mask_phone("") == ""
    assert mask_phone("12") == "**"
    assert mask_phone("123") == "1*3"


def test_mask_name_keeps_surname_only() -> None:
    assert mask_name("张先生") == "张**"
    assert mask_name("李女士") == "李**"
    assert mask_name("王") == "*"
    assert mask_name(None) == ""


def test_mask_address_keeps_region_and_hides_detail() -> None:
    address = {"province": "北京市", "city": "北京市", "detail": "朝阳区建国路88号"}
    assert mask_address(address) == "北京市朝阳区***"

    assert mask_address({"province": "广东省", "city": "深圳市", "detail": "南山区科技园"}) == (
        "广东省深圳市南山区***"
    )


def test_mask_address_handles_strings_and_empty_values() -> None:
    assert mask_address("上海市浦东新区世纪大道1000号") == "上海市浦东新***"
    assert mask_address("上海市浦东") == "上海***"
    assert mask_address("") == ""
    assert mask_address(None) == ""
