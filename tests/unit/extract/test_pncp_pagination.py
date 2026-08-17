import pytest

from govinsight.extract.pncp.errors import PNCPResponseError
from govinsight.extract.pncp.models import PNCPPage
from govinsight.extract.pncp.pagination import iter_pages, iter_records


def page(number: int, total: int, ids: list[str]) -> PNCPPage:
    return PNCPPage(
        data=[{"numeroControlePNCP": record_id} for record_id in ids],
        total_records=sum([2, 1, 1][:total]),
        total_pages=total,
        page_number=number,
        remaining_pages=total - number,
        empty=False,
    )


def test_iter_pages_requests_each_page_once_in_order() -> None:
    requested: list[int] = []
    responses = {
        1: page(1, 3, ["A", "B"]),
        2: page(2, 3, ["C"]),
        3: page(3, 3, ["D"]),
    }

    def fetch_page(number: int) -> PNCPPage:
        requested.append(number)
        return responses[number]

    pages = list(iter_pages(fetch_page))

    assert requested == [1, 2, 3]
    assert [item.page_number for item in pages] == [1, 2, 3]


def test_iter_records_yields_each_record_once_in_source_order() -> None:
    responses = {
        1: page(1, 2, ["A", "B"]),
        2: page(2, 2, ["C"]),
    }

    records = list(iter_records(responses.__getitem__))

    assert [record["numeroControlePNCP"] for record in records] == ["A", "B", "C"]


def test_empty_first_page_stops_without_requesting_a_second_page() -> None:
    requested: list[int] = []

    def fetch_page(number: int) -> PNCPPage:
        requested.append(number)
        return PNCPPage.empty_page(number)

    assert list(iter_records(fetch_page)) == []
    assert requested == [1]


def test_mismatched_response_page_is_rejected_before_duplicate_data_can_be_yielded() -> None:
    def fetch_page(_number: int) -> PNCPPage:
        return page(1, 3, ["A"])

    iterator = iter_pages(fetch_page, start_page=2)

    with pytest.raises(PNCPResponseError, match="unexpected page number"):
        next(iterator)


def test_start_page_must_be_positive() -> None:
    with pytest.raises(ValueError, match="start_page"):
        list(iter_pages(lambda number: PNCPPage.empty_page(number), start_page=0))
