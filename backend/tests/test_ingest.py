from pathlib import Path

from app.services.ingest import parse_document, sync_tenant

ROOT = Path(__file__).resolve().parent.parent


def test_faq_pdf_parses_all_pairs():
    ps = parse_document(ROOT / "knowledge/zenshine/faq.pdf", "zenshine")
    assert len(ps) > 700
    assert all(p.text.startswith("Q: ") and "\nA: " in p.text for p in ps)
    assert len({p.id for p in ps}) == len(ps)


async def test_sync_is_idempotent_and_cleans_stale(store, tmp_path):
    kd = tmp_path / "k" / "t"
    kd.mkdir(parents=True)
    f = kd / "doc.txt"
    f.write_text(
        "Question: What is A? Answer: Alpha is the first letter of the alphabet.\n\nQuestion: What is B? Answer: Bravo is the second letter."
    )
    r1 = await sync_tenant(store, tmp_path / "k", "t")
    assert r1.upserted == 2 and r1.deleted == 0
    r2 = await sync_tenant(store, tmp_path / "k", "t")
    assert r2.upserted == 0 and r2.unchanged == 2
    f.write_text("Question: What is A? Answer: Alpha is the first letter of the alphabet.\n")
    r3 = await sync_tenant(store, tmp_path / "k", "t")
    assert r3.deleted == 1 and await store.count("t") == 1
