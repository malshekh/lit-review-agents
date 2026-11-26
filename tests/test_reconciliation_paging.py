from decimal import Decimal

import pytest

from litreview.reconciliation_paging import check_spend


def test_increment_includes_previous_charges_and_open_reservations():
    approval = {"baseline_stage_usd": "2.7465485", "max_increment_usd": "4.949984"}
    check_spend(approval, Decimal("3.7465485"), Decimal("3.949984"))
    with pytest.raises(ValueError, match="incremental reservation"):
        check_spend(approval, Decimal("3.7465485"), Decimal("3.949985"))


def test_ledger_rollback_cannot_create_new_headroom():
    with pytest.raises(ValueError, match="incremental reservation"):
        check_spend({"baseline_stage_usd": "2", "max_increment_usd": "1"}, Decimal("1"), Decimal("1"))
