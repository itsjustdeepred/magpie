import re

from magpie.i18n import MESSAGES


def test_catalogs_have_the_same_keys():
    en = set(MESSAGES["en"])
    for lang, catalog in MESSAGES.items():
        assert set(catalog) == en, lang


def test_translations_use_the_same_placeholders():
    for key, text in MESSAGES["en"].items():
        wanted = set(re.findall(r"{(\w+)}", text))
        for lang, catalog in MESSAGES.items():
            assert set(re.findall(r"{(\w+)}", catalog[key])) == wanted, (lang, key)
