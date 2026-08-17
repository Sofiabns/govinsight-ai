from collections.abc import Callable, Iterator
from typing import Any

from govinsight.extract.pncp.errors import PNCPResponseError
from govinsight.extract.pncp.models import PNCPPage

PageFetcher = Callable[[int], PNCPPage]


def iter_pages(fetch_page: PageFetcher, *, start_page: int = 1) -> Iterator[PNCPPage]:
    if start_page < 1:
        raise ValueError("start_page must be positive")

    requested_page = start_page
    while True:
        page = fetch_page(requested_page)
        if page.page_number != requested_page:
            raise PNCPResponseError(
                endpoint="pagination",
                reason=(f"unexpected page number {page.page_number}; requested {requested_page}"),
            )

        yield page
        if page.empty or page.remaining_pages == 0 or page.page_number >= page.total_pages:
            return
        requested_page += 1


def iter_records(fetch_page: PageFetcher, *, start_page: int = 1) -> Iterator[dict[str, Any]]:
    for page in iter_pages(fetch_page, start_page=start_page):
        yield from page.data
