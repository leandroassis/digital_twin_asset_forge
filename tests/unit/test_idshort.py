from basyx.aas import model

from asset_forge.export.aas.idshort import unique_id_shorts, valid_id_short


def test_already_valid_name_is_left_alone():
    assert valid_id_short("PumpP101") == "PumpP101"


def test_non_ascii_and_punctuation_get_replaced():
    slug = valid_id_short("Öl-Brennwertkessel #12")
    model.AssetAdministrationShell.validate_id_short(slug)


def test_digit_leading_candidate_gets_a_letter_prefix():
    slug = valid_id_short("3M7BrgwhP5MQMQ$fudrMnF")
    assert slug[0].isalpha()
    model.AssetAdministrationShell.validate_id_short(slug)


def test_trailing_hyphen_is_stripped():
    slug = valid_id_short("Pump-")
    assert not slug.endswith("-")
    model.AssetAdministrationShell.validate_id_short(slug)


def test_empty_candidate_falls_back_to_the_given_fallback():
    assert valid_id_short("", fallback="Asset") == "Asset"
    model.AssetAdministrationShell.validate_id_short(valid_id_short(""))


def test_leading_hash_property_name_gets_a_valid_prefix():
    # Real-world vendor pset property names look like this (e.g. SmartPlant
    # 3D's "#Object Class").
    slug = valid_id_short("#Object Class", fallback="Prop")
    model.AssetAdministrationShell.validate_id_short(slug)


def test_unique_id_shorts_disambiguates_collisions():
    slugs = unique_id_shorts(["Object Class", "Object_Class", "Object-Class"], fallback="Prop")

    assert len(set(slugs.values())) == 3
    for slug in slugs.values():
        model.AssetAdministrationShell.validate_id_short(slug)


def test_unique_id_shorts_is_stable_for_already_unique_names():
    slugs = unique_id_shorts(["Foo", "Bar", "Baz"], fallback="Prop")

    assert slugs == {"Foo": "Foo", "Bar": "Bar", "Baz": "Baz"}
