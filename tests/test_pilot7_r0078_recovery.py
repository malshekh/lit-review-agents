import json
import pytest
from scripts.recover_pilot7_r0078 import legends, restore_quote, pca_cell


def test_range_requires_all_six_legend_ids_and_original_text():
    s={}
    for n in range(1,7):
        s[f"Figure legend {n}"]=json.dumps({"id":f"fig{n}","label":str(n),"legend":"caption"})
        s[f"Verbatim figure legend {n}"]="caption"
    assert len(legends(s))==6
    s["Figure legend 4"]=s["Figure legend 5"]
    with pytest.raises(ValueError): legends(s)


def test_quote_requires_unique_exact_source_with_both_characters():
    q="structurespecifically ... idarubicinwhich"
    exact="structure\ue5f8specifically ... idarubicin\ue5f8which"
    assert restore_quote(q,exact)[0]==exact
    for source in (exact+exact,q):
        with pytest.raises(ValueError):restore_quote(q,source)


def test_blue_dissociation_cell_cannot_fill_pca_column():
    with pytest.raises(ValueError):
        pca_cell({"Table 1 | Daunorubicin | Concentration-based PCA":
                  "Daunorubicin | Dissociation constant | GGACGC-(8,7) | blue | intensity change"})

