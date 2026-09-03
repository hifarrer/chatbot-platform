"""Generate the Northwind Coffee Roasters sample training corpus.

These are QA fixtures, not customer data. Every document carries at least one
uniquely-worded fact so a trained bot's answer can be asserted on an exact
string instead of eyeballed:

    northwind_faq.txt        order code NW-4471   -> ships in 2 business days
    northwind_handbook.pdf   return policy PX-820 -> 45 days, buried on page 4
    northwind_products.docx  Aurora burr grinder  -> $284.50
    northwind_catalog.json   sku KL-9006
    northwind_pricing.xlsx   wholesale tier 3     -> $18.75 per lb

The PDF is deliberately multi-page: page joins are where the extractor's
newline handling shows up, and a fact buried mid-document is what catches a
map-reduce that silently drops a middle batch.

Run:  python sample_docs/generate.py
Needs reportlab, python-docx and openpyxl. reportlab is fixture-only tooling
and is deliberately not in requirements.txt.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def out(name):
    return os.path.join(HERE, name)


# ---------------------------------------------------------------- txt

FAQ = """Northwind Coffee Roasters - Customer FAQ

Q: Where do you roast?
A: Every bag is roasted in our Ballard facility in Seattle, Washington, in
   batches of no more than 12 kilograms.

Q: How fresh is the coffee when it ships?
A: We roast to order. Beans leave the roastery within 24 hours of roasting.

Q: How fast is standard shipping?
A: Orders placed with order code NW-4471 ship in 2 business days. Standard
   orders without that code ship in 4 to 6 business days.

Q: Do you ship internationally?
A: We ship to Canada and Mexico. We do not currently ship to Europe or Asia.

Q: What is your minimum wholesale order?
A: Twenty pounds per shipment, mixed origins allowed.

Q: Do you offer decaf?
A: Yes. Our Midnight Decaf is processed with the Swiss Water method and is
   available in 12 ounce retail bags only.

Q: Can I pause a subscription?
A: Yes, from the account page. A paused subscription is never billed.

Q: What grind options are there?
A: Whole bean, drip, French press, and espresso. Whole bean is the default.

Q: Do you sell gift cards?
A: Yes, in 25, 50 and 100 dollar denominations. Gift cards do not expire.

Q: How should I store the beans?
A: In an airtight container at room temperature, away from sunlight. Do not
   refrigerate.

Q: Who do I contact about a damaged shipment?
A: Email support@northwindroasters.example within 7 days of delivery and we
   will replace the order.

Q: Do you have a physical storefront?
A: Yes, one cafe attached to the roastery. It is open 7am to 3pm on weekdays
   and 8am to 2pm on weekends.

Q: Is your packaging recyclable?
A: The bags are LDPE 4 and the valves are polypropylene. Both are accepted by
   the Seattle curbside program.
"""


def write_txt():
    path = out('northwind_faq.txt')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(FAQ)
    return path


# ---------------------------------------------------------------- pdf

PDF_PAGES = [
    ('1. About Northwind Coffee Roasters', """
    Northwind Coffee Roasters was founded in 2009 as a two-person operation
    working out of a rented commissary kitchen. Today the company employs
    thirty-one people across the roastery, the cafe and the wholesale team.
    This handbook is the internal reference for anyone answering customer
    questions, whether over email, on the phone or at the counter.

    Our sourcing model is direct trade. We buy from eleven producer partners
    across Ethiopia, Colombia, Guatemala and Sumatra, and we publish the price
    paid per pound of green coffee for every lot we buy. Contracts are signed
    annually in October and cover the following harvest year.

    Roasting happens on a 12 kilogram Loring Smart Roast. Every batch is
    logged: charge temperature, development time, and end temperature. Batch
    logs are retained for three years and are available to any wholesale
    partner on request.
    """),
    ('2. Ordering and fulfilment', """
    Retail orders are placed through the website and are picked the same day
    they are roasted. The roast schedule runs Tuesday through Saturday, so an
    order placed on Sunday enters the Tuesday roast.

    Wholesale orders are placed by the account manager through the partner
    portal. The minimum wholesale order is twenty pounds per shipment and may
    be mixed across origins. Wholesale invoices are net thirty.

    Subscription orders renew on the same calendar day each month. A customer
    may pause, skip or cancel a subscription at any time before the renewal
    date without penalty. A paused subscription is never billed and does not
    count against the annual loyalty tier calculation.

    Shipping is calculated by weight, not by order value. Orders over fifty
    dollars ship free within the continental United States.
    """),
    ('3. Quality control', """
    Every lot is cupped twice: once on arrival as green coffee, and once
    forty-eight hours after roasting. Cupping scores are recorded on the SCA
    hundred point scale. We do not release any lot scoring below eighty-four.

    Moisture content of green coffee is measured on arrival and must fall
    between ten and twelve percent. Anything outside that band is rejected and
    returned to the importer at their cost.

    Water used in the cafe and on the cupping table is filtered and
    remineralised to a target of one hundred and fifty parts per million total
    dissolved solids. The filter cartridges are replaced every ninety days.

    Grinders are calibrated at open and at close. Burr sets are replaced after
    six hundred kilograms of throughput, which for the cafe is roughly annually.
    """),
    ('4. Returns, refunds and the satisfaction guarantee', """
    Northwind operates under return policy PX-820. Under return policy PX-820 a
    customer may return any unopened retail bag within 45 days of the delivery
    date for a full refund, and we pay the return shipping. The 45 day window
    under PX-820 applies to retail orders only.

    Opened bags are covered by the separate satisfaction guarantee: if a
    customer does not like the coffee, we replace it once with a different
    origin at no charge. There is no requirement to return the opened bag.

    Wholesale returns are handled case by case by the account manager and are
    not covered by PX-820. Damaged shipments must be reported within seven days
    of delivery, with photographs, and are replaced rather than refunded.

    Refunds are issued to the original payment method and take three to five
    business days to appear. Gift card purchases are non-refundable but never
    expire.
    """),
    ('5. The cafe', """
    The cafe is attached to the roastery and shares its ventilation, which is
    why the espresso bar closes for twenty minutes during any roast that runs
    past two in the afternoon.

    Opening hours are seven in the morning until three in the afternoon on
    weekdays, and eight until two at weekends. The cafe is closed on New Year
    Day, Thanksgiving and Christmas Day.

    The espresso menu is deliberately short: espresso, macchiato, cortado, flat
    white, latte. There is no flavoured syrup on the menu and there has not
    been since 2014. Oat, soy and whole milk are offered at no price
    difference.

    Staff are trained on a four week rotation covering brewing, extraction
    theory, milk technique and customer service. Every new hire cups with the
    quality team in their first week.
    """),
    ('6. Sustainability and packaging', """
    Retail bags are LDPE 4 with a polypropylene one-way valve. Both are
    accepted by the Seattle curbside recycling program. Wholesale coffee ships
    in five pound kraft bags with a recyclable liner.

    Spent grounds from the cafe are collected daily by an urban farm
    cooperative. In 2024 that diverted just over eleven tonnes from landfill.

    The roastery runs on a hundred percent renewable electricity contract. The
    roaster itself is gas fired; we offset its emissions through a verified
    reforestation programme and publish the certificates annually.

    Our long term goal is a fully compostable retail bag. We have tested four
    candidate materials and none has yet held a twelve month shelf life, so we
    have not switched.
    """),
]


def write_pdf():
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    path = out('northwind_handbook.pdf')
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        path, pagesize=LETTER, title='Northwind Coffee Roasters Handbook')
    blank_line = chr(10) + chr(10)
    story = []
    for index, (heading, body) in enumerate(PDF_PAGES):
        story.append(Paragraph(heading, styles['Heading1']))
        story.append(Spacer(1, 10))
        for para in body.strip().split(blank_line):
            story.append(Paragraph(' '.join(para.split()), styles['BodyText']))
            story.append(Spacer(1, 8))
        if index < len(PDF_PAGES) - 1:
            story.append(PageBreak())
    doc.build(story)
    return path


# ---------------------------------------------------------------- docx

DOCX_SECTIONS = [
    ('Brewing equipment', [
        'The Aurora burr grinder retails at $284.50 and is our best selling piece '
        'of equipment. It has 40 millimetre conical burrs, stepless adjustment '
        'and a single dose hopper. The Aurora burr grinder is sold with a two '
        'year warranty.',
        'The Cascade pour-over kettle retails at $89.00. It holds one litre, has '
        'a gooseneck spout and holds temperature to within one degree for twenty '
        'minutes.',
        'The Meridian espresso tamper retails at $46.00 and is machined to 58.5 '
        'millimetres. It is the tamper used on the cafe bar.',
    ]),
    ('Subscription tiers', [
        'The Explorer subscription is one twelve ounce bag per month at $22.00 '
        'and rotates through whatever single origin we are most excited about.',
        'The Regular subscription is two twelve ounce bags per month at $40.00 '
        'and the customer picks the origins.',
        'The Cafe subscription is five pounds per month at $96.00 and is intended '
        'for offices. It ships whole bean by default.',
    ]),
    ('Care and maintenance', [
        'Burr grinders should be brushed out weekly and fully disassembled and '
        'cleaned every three months. Do not put burrs in a dishwasher.',
        'Kettles should be descaled every two months in a hard water area and '
        'every six months elsewhere. Use a citric acid solution, never vinegar.',
        'Tampers need nothing beyond a wipe with a dry cloth. Do not soak the '
        'handle if it is wood.',
    ]),
]


def write_docx():
    import docx

    path = out('northwind_products.docx')
    document = docx.Document()
    document.add_heading('Northwind Coffee Roasters - Product Sheet', level=1)
    document.add_paragraph(
        'Retail prices below are current as of this printing and exclude sales '
        'tax. Wholesale partners should refer to the pricing workbook instead.')
    for heading, paragraphs in DOCX_SECTIONS:
        document.add_heading(heading, level=2)
        for para in paragraphs:
            document.add_paragraph(para)
    document.save(path)
    return path


# ---------------------------------------------------------------- json

CATALOG = {
    'company': 'Northwind Coffee Roasters',
    'catalog_version': '2026.1',
    'currency': 'USD',
    'products': [
        {
            'sku': 'KL-9006',
            'name': 'Kilimanjaro Light',
            'origin': 'Tanzania',
            'process': 'washed',
            'roast_level': 'light',
            'tasting_notes': ['blackcurrant', 'cocoa nib', 'orange peel'],
            'sizes': [
                {'weight_oz': 12, 'price': 21.0},
                {'weight_lb': 5, 'price': 96.0},
            ],
            'seasonal': True,
            'notes': 'SKU KL-9006 is the Kilimanjaro Light and is available from '
                     'March through September only.',
        },
        {
            'sku': 'ET-2210',
            'name': 'Yirgacheffe Reserve',
            'origin': 'Ethiopia',
            'process': 'natural',
            'roast_level': 'light',
            'tasting_notes': ['strawberry', 'jasmine', 'honey'],
            'sizes': [{'weight_oz': 12, 'price': 24.0}],
            'seasonal': False,
        },
        {
            'sku': 'CO-1180',
            'name': 'Huila Comfort',
            'origin': 'Colombia',
            'process': 'washed',
            'roast_level': 'medium',
            'tasting_notes': ['caramel', 'red apple', 'almond'],
            'sizes': [
                {'weight_oz': 12, 'price': 19.0},
                {'weight_lb': 5, 'price': 84.0},
            ],
            'seasonal': False,
        },
        {
            'sku': 'DC-0440',
            'name': 'Midnight Decaf',
            'origin': 'blend',
            'process': 'swiss water',
            'roast_level': 'dark',
            'tasting_notes': ['dark chocolate', 'molasses'],
            'sizes': [{'weight_oz': 12, 'price': 20.0}],
            'seasonal': False,
        },
    ],
    'shipping': {
        'free_threshold_usd': 50,
        'domestic_carriers': ['USPS', 'UPS'],
        'international': ['CA', 'MX'],
    },
}


def write_json():
    path = out('northwind_catalog.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(CATALOG, fh, indent=2)
    return path


# ---------------------------------------------------------------- xlsx

WHOLESALE_ROWS = [
    ['Tier', 'Minimum pounds per month', 'Price per lb', 'Payment terms'],
    ['Tier 1', 20, 24.50, 'net 15'],
    ['Tier 2', 60, 21.25, 'net 30'],
    ['Tier 3', 150, 18.75, 'net 30'],
    ['Tier 4', 400, 16.40, 'net 45'],
]

RETAIL_ROWS = [
    ['SKU', 'Product', 'Size', 'Retail price'],
    ['KL-9006', 'Kilimanjaro Light', '12 oz', 21.00],
    ['ET-2210', 'Yirgacheffe Reserve', '12 oz', 24.00],
    ['CO-1180', 'Huila Comfort', '12 oz', 19.00],
    ['DC-0440', 'Midnight Decaf', '12 oz', 20.00],
    ['KL-9006', 'Kilimanjaro Light', '5 lb', 96.00],
    ['CO-1180', 'Huila Comfort', '5 lb', 84.00],
]


def write_xlsx():
    from openpyxl import Workbook

    path = out('northwind_pricing.xlsx')
    wb = Workbook()
    ws = wb.active
    ws.title = 'Wholesale'
    for row in WHOLESALE_ROWS:
        ws.append(row)
    ws.append([])
    ws.append(['Note', 'Wholesale tier 3 is $18.75 per lb at 150 lb per month.'])

    ws2 = wb.create_sheet('Retail')
    for row in RETAIL_ROWS:
        ws2.append(row)
    wb.save(path)
    return path


def main():
    for writer in (write_txt, write_pdf, write_docx, write_json, write_xlsx):
        path = writer()
        print('%-30s %8d bytes' % (os.path.basename(path), os.path.getsize(path)))


if __name__ == '__main__':
    main()
