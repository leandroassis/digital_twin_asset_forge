from asset_forge.ingestion.loader import _escape_bare_backslashes


def test_legitimate_step_shift_escape_survives_untouched():
    # \S\V shifts 'V' up by 128 -- this is how the real HVAC/VDI3805 sample
    # in assets/ encodes the German "Öl-Brennwertkessel" (oil condensing
    # boiler). Doubling it would desync the decoder and corrupt the text.
    text = r"#101, '\S\Vl-Brennwertkessel'"
    assert _escape_bare_backslashes(text) == text


def test_legitimate_x2_unicode_run_escape_survives_untouched():
    text = r"'prefix \X2\00D600F6\X0\ suffix'"
    assert _escape_bare_backslashes(text) == text


def test_bare_windows_path_backslashes_get_doubled():
    text = r"'C:\Users\jdoe\proteus_converter'"
    assert _escape_bare_backslashes(text) == r"'C:\\Users\\jdoe\\proteus_converter'"


def test_bare_backslash_next_to_a_legitimate_escape_is_still_doubled():
    text = r"'\S\Vfoo\bar'"
    # \S\V is a real escape (2 chars consumed: \S\ + the shifted char V);
    # the second backslash, before "bar", is a bare one and must double.
    assert _escape_bare_backslashes(text) == r"'\S\Vfoo\\bar'"
