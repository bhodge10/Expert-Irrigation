"""Tests for the parsing layer, against shapes taken from real office mail."""

from app.mail.cleaning import (
    clean_for_classification,
    strip_form_boilerplate,
    strip_quoted,
    strip_signature,
)
from app.mail.forms import detect_form_type, parse_form
from app.mail.forwards import looks_forwarded, parse_forwarded, strip_forward_prefix
from app.mail.html_text import best_body, html_to_text
from app.models import FORM_CONTACT, FORM_INSTALL, FORM_SERVICE

from . import fixtures as fx


# --- HTML ----------------------------------------------------------------

def test_html_body_is_used_when_plain_text_is_empty():
    """Every real sample had an empty plain-text body. This is the normal path."""
    html = "<html><body><p>Zone 4 won't come on.</p><p>Doug</p></body></html>"
    # Separate paragraphs stay separated — that's how the office will read it.
    assert best_body("", html) == "Zone 4 won't come on.\n\nDoug"


def test_leading_meta_tag_does_not_swallow_the_body():
    """Regression. Every real Outlook body opens with a bare <meta charset>.

    <meta> is a void element, so treating it as skippable opened a region that
    never closed and blanked the entire message. Tidy fixtures passed while
    every genuine email produced an empty string.
    """
    html = (
        '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
        "First Name: David<br>Last Name: Kaylor<br>Phone: 5135550188"
    )
    text = html_to_text(html)
    assert "First Name: David" in text
    assert "Kaylor" in text


def test_reply_quoting_a_form_is_not_itself_a_form():
    """"Re: New Website Form Inquiry" is what the office's own replies look
    like for weeks afterwards. Treating those as new submissions would fill
    the queue with the office talking to itself."""
    reply_text = "Got it, thanks.\n\nCraig"
    assert detect_form_type("Re: New Website Form Inquiry", reply_text) is None


def test_html_script_and_style_are_dropped():
    html = "<style>p{color:red}</style><p>Real content</p><script>x=1</script>"
    assert html_to_text(html) == "Real content"


def test_outlook_padding_collapses():
    html = "<p>One</p><p></p><p></p><p></p><p></p><p>Two</p>"
    assert html_to_text(html) == "One\n\nTwo"


def test_nbsp_and_zero_width_characters_go():
    assert html_to_text("<p>a&nbsp;&nbsp;b‌</p>") == "a b"


def test_malformed_html_still_yields_text():
    assert "Leak" in html_to_text("<p>Leak <b>here")


# --- quoting -------------------------------------------------------------

def test_quoted_history_is_cut_at_the_header_block():
    result = strip_quoted(fx.THREADED_REPLY["body"])
    assert "Thanks for the pictures." in result
    assert "Not sure of any model" not in result
    assert "Sent: Wednesday, May 6" not in result


def test_on_wrote_banner_is_cut():
    text = "Sounds good.\n\nOn May 6, 2026, at 8:42 AM, Craig Zumdick <c@x.com> wrote:\n\nOlder text"
    assert strip_quoted(text) == "Sounds good."


def test_prose_beginning_with_from_is_not_treated_as_a_quote():
    """A bare 'From:' needs a second header nearby before we believe it."""
    text = "From: the back yard, the water is pooling badly.\nPlease send someone."
    assert strip_quoted(text) == text


def test_angle_bracket_quoting_is_cut():
    assert strip_quoted("New bit.\n> old bit\n> older bit") == "New bit."


# --- signatures ----------------------------------------------------------

def test_company_signature_is_removed():
    result = strip_signature(strip_quoted(fx.THREADED_REPLY["body"]))
    assert "Thanks for the pictures." in result
    assert "www.expertsvc.com" not in result
    assert "(859) 282-8101" not in result


def test_thank_you_for_choosing_opener_cuts_the_block():
    result = strip_signature(strip_quoted(fx.INTERNAL_REPLY["body"]))
    assert "Billy scheduled" in result
    assert "Google review" not in result
    assert "Customer Service Representative" not in result


def test_message_ending_in_prose_is_left_alone():
    text = "Zones 1 through 3 run fine but zone 4 does nothing, no water at all."
    assert strip_signature(text) == text


def test_a_lone_phone_number_is_not_a_signature():
    """One contact detail is how customers end mail; don't eat their content."""
    text = "Please call me to arrange a visit.\n859-555-0133"
    assert "859-555-0133" in strip_signature(text)


# --- form boilerplate ----------------------------------------------------

def test_virtual_estimate_boilerplate_is_removed():
    """Left in, this lighting pitch appears on every form and drags Sales."""
    cleaned = strip_form_boilerplate(fx.CONTACT_FORM_LEAK["body"])
    assert "Virtual Estimate" not in cleaned
    assert "large leak" in cleaned


def test_form_trailer_is_removed():
    cleaned = strip_form_boilerplate(fx.CONTACT_FORM_LEAK["body"])
    assert "Page URL" not in cleaned
    assert "Time: 1:47 am" not in cleaned


# --- the combined clean --------------------------------------------------

def test_clean_keeps_the_request_and_drops_everything_else():
    cleaned = clean_for_classification(fx.THREADED_REPLY["body"])
    assert "Estimate for the new sensor" in cleaned
    assert "www.expertsvc.com" not in cleaned
    assert "Not sure of any model" not in cleaned


def test_clean_never_returns_nothing():
    """A terse reply over a long quote must not clean down to an empty string."""
    text = "Got it, thanks.\n\nCraig\n\nFrom: Joyce\nSent: Thursday\nTo: Craig\n\nlong history here"
    assert clean_for_classification(text).strip()


# --- form detection and parsing ------------------------------------------

def test_each_form_is_detected():
    assert detect_form_type(fx.CONTACT_FORM_LEAK["subject"], fx.CONTACT_FORM_LEAK["body"]) == FORM_CONTACT
    assert detect_form_type(fx.INSTALL_FORM["subject"], fx.INSTALL_FORM["body"]) == FORM_INSTALL
    assert detect_form_type(fx.SERVICE_FORM["subject"], fx.SERVICE_FORM["body"]) == FORM_SERVICE


def test_ordinary_mail_is_not_a_form():
    assert detect_form_type(fx.DIRECT_URGENT["subject"], fx.DIRECT_URGENT["body"]) is None


def test_new_customer_forms_are_told_apart_without_the_subject():
    """Both share a Page URL, so the body has to break the tie."""
    assert detect_form_type("", fx.INSTALL_FORM["body"]) == FORM_INSTALL
    assert detect_form_type("", fx.SERVICE_FORM["body"]) == FORM_SERVICE


def test_contact_form_recovers_the_real_customer():
    """The whole point: the From header says website@, the customer is inside."""
    parsed = parse_form(fx.CONTACT_FORM_LEAK["subject"], fx.CONTACT_FORM_LEAK["body"])
    assert parsed.confident
    assert parsed.from_name == "Dana Whitfield"
    assert parsed.from_email == "dwhitfield@example.com"
    assert parsed.phone == "5135550142"
    assert "118 Marston Ave" in parsed.address
    assert "large leak" in parsed.message
    assert "Virtual Estimate" not in parsed.message


def test_contact_form_with_shuffled_fields_refuses_to_guess():
    """Better to flag it than to file the phone number as the customer name."""
    parsed = parse_form(
        fx.CONTACT_FORM_MALFORMED["subject"], fx.CONTACT_FORM_MALFORMED["body"]
    )
    assert not parsed.confident
    assert parsed.from_email == ""
    assert "back zone" in parsed.message


def test_install_form_fields():
    parsed = parse_form(fx.INSTALL_FORM["subject"], fx.INSTALL_FORM["body"])
    assert parsed.confident
    assert parsed.from_name == "Nathan Cole"
    assert parsed.from_email == "ncole@example.com"
    assert "Tired of dragging a hose" in parsed.message
    assert "734 Stonehill Run" in parsed.address


def test_service_form_folds_the_state_sublines():
    """'City and state' is a header; the answer is on the KY:/OH:/IN: lines."""
    parsed = parse_form(fx.SERVICE_FORM["subject"], fx.SERVICE_FORM["body"])
    assert parsed.from_name == "Brian Teague"
    assert "Union, KY" in parsed.address
    assert "OH" not in parsed.address
    assert "fence installed" in parsed.message


# --- forwards ------------------------------------------------------------

def test_forward_is_recognised():
    assert looks_forwarded(fx.FORWARDED_HOA["subject"], fx.FORWARDED_HOA["body"])
    assert not looks_forwarded(fx.DIRECT_URGENT["subject"], fx.DIRECT_URGENT["body"])


def test_forward_prefixes_are_stripped():
    assert strip_forward_prefix("FW: Fwd: Leak") == "Leak"
    assert strip_forward_prefix("Re: Leak") == "Re: Leak"


def test_forward_recovers_the_original_sender():
    original = parse_forwarded(fx.FORWARDED_HOA["subject"], fx.FORWARDED_HOA["body"])
    assert original.confident
    assert original.from_email == "aprescott@example.com"
    assert original.from_name == "Alan Prescott"
    assert original.subject == "ABERDEEN- Union KY."
    assert "active leak" in original.body
    # The forwarder's own covering note isn't part of the original.
    assert "I am not sure if you/Expert are aware" not in original.body


def test_forward_survives_a_missing_header_block():
    """Contract: a failed parse still yields a usable message, flagged."""
    original = parse_forwarded("FW: Leak at the corner", "Craig - see this one.\n\nThanks")
    assert not original.confident
    assert original.subject == "Leak at the corner"
    assert "see this one" in original.body
