"""
Extended Universe — Top 100 small/mid-cap names beyond the ledger's 33 picks.
These get a brief Claude analysis daily for on-search verdicts.

Curated to span: banking, NBFC, capital goods, defence, chemicals, pharma,
healthcare, IT, auto-anc, infra, FMCG, building-materials, capital-markets.
Excludes the 33 ledger names.
"""

EXTENDED_UNIVERSE_STOCKS = [
    # ========== MID-CAPS (~50) ==========

    # Banking & NBFC
    {"symbol": "AUBANK.NS",     "ticker": "AUBANK",     "name": "AU Small Finance Bank",      "sector": "Banking"},
    {"symbol": "BANDHANBNK.NS", "ticker": "BANDHANBNK", "name": "Bandhan Bank",                "sector": "Banking"},
    {"symbol": "IDFCFIRSTB.NS", "ticker": "IDFCFIRSTB", "name": "IDFC First Bank",             "sector": "Banking"},
    {"symbol": "FEDERALBNK.NS", "ticker": "FEDERALBNK", "name": "Federal Bank",                "sector": "Banking"},
    {"symbol": "CANBK.NS",      "ticker": "CANBK",      "name": "Canara Bank",                 "sector": "PSU Banking"},
    {"symbol": "PNB.NS",        "ticker": "PNB",        "name": "Punjab National Bank",        "sector": "PSU Banking"},
    {"symbol": "MUTHOOTFIN.NS", "ticker": "MUTHOOTFIN", "name": "Muthoot Finance",             "sector": "NBFC"},
    {"symbol": "CHOLAFIN.NS",   "ticker": "CHOLAFIN",   "name": "Cholamandalam Investment",    "sector": "NBFC"},
    {"symbol": "SHRIRAMFIN.NS", "ticker": "SHRIRAMFIN", "name": "Shriram Finance",             "sector": "NBFC"},
    {"symbol": "M&MFIN.NS",     "ticker": "M&MFIN",     "name": "M&M Financial Services",      "sector": "NBFC"},

    # IT / Tech
    {"symbol": "PERSISTENT.NS", "ticker": "PERSISTENT", "name": "Persistent Systems",          "sector": "Information Technology"},
    {"symbol": "MPHASIS.NS",    "ticker": "MPHASIS",    "name": "Mphasis",                     "sector": "Information Technology"},
    {"symbol": "LTTS.NS",       "ticker": "LTTS",       "name": "L&T Technology Services",     "sector": "Information Technology"},
    {"symbol": "KPITTECH.NS",   "ticker": "KPITTECH",   "name": "KPIT Technologies",           "sector": "Auto Tech"},
    {"symbol": "TATAELXSI.NS",  "ticker": "TATAELXSI",  "name": "Tata Elxsi",                  "sector": "Information Technology"},

    # Auto / Auto-ancillaries
    {"symbol": "BHARATFORG.NS", "ticker": "BHARATFORG", "name": "Bharat Forge",                "sector": "Auto Ancillary"},
    {"symbol": "SONACOMS.NS",   "ticker": "SONACOMS",   "name": "Sona BLW Precision Forgings", "sector": "Auto Ancillary"},
    {"symbol": "SCHAEFFLER.NS", "ticker": "SCHAEFFLER", "name": "Schaeffler India",            "sector": "Auto Ancillary"},
    {"symbol": "TIINDIA.NS",    "ticker": "TIINDIA",    "name": "Tube Investments of India",   "sector": "Auto Ancillary"},
    {"symbol": "TVSMOTOR.NS",   "ticker": "TVSMOTOR",   "name": "TVS Motor Company",           "sector": "Auto"},

    # Capital Goods / Engineering
    {"symbol": "CUMMINSIND.NS", "ticker": "CUMMINSIND", "name": "Cummins India",               "sector": "Capital Goods"},
    {"symbol": "POLYCAB.NS",    "ticker": "POLYCAB",    "name": "Polycab India",               "sector": "Cables / Wires"},
    {"symbol": "HAVELLS.NS",    "ticker": "HAVELLS",    "name": "Havells India",               "sector": "Electrical"},
    {"symbol": "ABB.NS",        "ticker": "ABB",        "name": "ABB India",                   "sector": "Capital Goods"},
    {"symbol": "SIEMENS.NS",    "ticker": "SIEMENS",    "name": "Siemens",                     "sector": "Capital Goods"},

    # Consumer / FMCG
    {"symbol": "VOLTAS.NS",     "ticker": "VOLTAS",     "name": "Voltas",                      "sector": "Consumer Durables"},
    {"symbol": "CROMPTON.NS",   "ticker": "CROMPTON",   "name": "Crompton Greaves Consumer",   "sector": "Consumer Durables"},
    {"symbol": "WHIRLPOOL.NS",  "ticker": "WHIRLPOOL",  "name": "Whirlpool India",             "sector": "Consumer Durables"},
    {"symbol": "JUBLFOOD.NS",   "ticker": "JUBLFOOD",   "name": "Jubilant FoodWorks",          "sector": "QSR / Restaurants"},
    {"symbol": "DABUR.NS",      "ticker": "DABUR",      "name": "Dabur India",                 "sector": "FMCG"},

    # Specialty Chemicals
    {"symbol": "PIIND.NS",      "ticker": "PIIND",      "name": "PI Industries",               "sector": "Specialty Chemicals"},
    {"symbol": "SRF.NS",        "ticker": "SRF",        "name": "SRF",                         "sector": "Specialty Chemicals"},
    {"symbol": "AARTIIND.NS",   "ticker": "AARTIIND",   "name": "Aarti Industries",            "sector": "Specialty Chemicals"},
    {"symbol": "NAVINFLUOR.NS", "ticker": "NAVINFLUOR", "name": "Navin Fluorine International","sector": "Specialty Chemicals"},

    # Energy / Gas / Utilities
    {"symbol": "GUJGASLTD.NS",  "ticker": "GUJGASLTD",  "name": "Gujarat Gas",                 "sector": "City Gas Distribution"},
    {"symbol": "IGL.NS",        "ticker": "IGL",        "name": "Indraprastha Gas",            "sector": "City Gas Distribution"},
    {"symbol": "PETRONET.NS",   "ticker": "PETRONET",   "name": "Petronet LNG",                "sector": "Gas"},
    {"symbol": "TATAPOWER.NS",  "ticker": "TATAPOWER",  "name": "Tata Power",                  "sector": "Power Utilities"},
    {"symbol": "NHPC.NS",       "ticker": "NHPC",       "name": "NHPC",                        "sector": "Power Utilities"},

    # Healthcare / Pharma
    {"symbol": "APOLLOHOSP.NS", "ticker": "APOLLOHOSP", "name": "Apollo Hospitals",            "sector": "Healthcare"},
    {"symbol": "MAXHEALTH.NS",  "ticker": "MAXHEALTH",  "name": "Max Healthcare Institute",    "sector": "Healthcare"},
    {"symbol": "FORTIS.NS",     "ticker": "FORTIS",     "name": "Fortis Healthcare",           "sector": "Healthcare"},
    {"symbol": "LUPIN.NS",      "ticker": "LUPIN",      "name": "Lupin",                       "sector": "Pharma"},
    {"symbol": "BIOCON.NS",     "ticker": "BIOCON",     "name": "Biocon",                      "sector": "Pharma / Biosimilars"},
    {"symbol": "ALKEM.NS",      "ticker": "ALKEM",      "name": "Alkem Laboratories",          "sector": "Pharma"},
    {"symbol": "AUROPHARMA.NS", "ticker": "AUROPHARMA", "name": "Aurobindo Pharma",            "sector": "Pharma"},
    {"symbol": "TORNTPHARM.NS", "ticker": "TORNTPHARM", "name": "Torrent Pharmaceuticals",     "sector": "Pharma"},
    {"symbol": "MANKIND.NS",    "ticker": "MANKIND",    "name": "Mankind Pharma",              "sector": "Pharma"},

    # Cement / Building Materials
    {"symbol": "ACC.NS",        "ticker": "ACC",        "name": "ACC",                         "sector": "Cement"},
    {"symbol": "AMBUJACEM.NS",  "ticker": "AMBUJACEM",  "name": "Ambuja Cements",              "sector": "Cement"},
    {"symbol": "DALBHARAT.NS",  "ticker": "DALBHARAT",  "name": "Dalmia Bharat",               "sector": "Cement"},
    {"symbol": "JKCEMENT.NS",   "ticker": "JKCEMENT",   "name": "JK Cement",                   "sector": "Cement"},
    {"symbol": "PIDILITIND.NS", "ticker": "PIDILITIND", "name": "Pidilite Industries",         "sector": "Adhesives / Sealants"},
    {"symbol": "BERGEPAINT.NS", "ticker": "BERGEPAINT", "name": "Berger Paints India",         "sector": "Paints"},

    # ========== SMALL-CAPS (~50) ==========

    # Capital Markets & Exchanges
    {"symbol": "CDSL.NS",       "ticker": "CDSL",       "name": "Central Depository Services", "sector": "Capital Markets"},
    {"symbol": "MCX.NS",        "ticker": "MCX",        "name": "Multi Commodity Exchange",    "sector": "Capital Markets"},
    {"symbol": "BSE.NS",        "ticker": "BSE",        "name": "BSE Limited",                 "sector": "Capital Markets"},
    {"symbol": "ANGELONE.NS",   "ticker": "ANGELONE",   "name": "Angel One",                   "sector": "Broking / Fintech"},
    {"symbol": "NUVAMA.NS",     "ticker": "NUVAMA",     "name": "Nuvama Wealth Management",    "sector": "Wealth Management"},

    # Defence & Railways
    {"symbol": "HAL.NS",        "ticker": "HAL",        "name": "Hindustan Aeronautics",       "sector": "Defence"},
    {"symbol": "MAZDOCK.NS",    "ticker": "MAZDOCK",    "name": "Mazagon Dock Shipbuilders",   "sector": "Defence Shipbuilding"},
    {"symbol": "COCHINSHIP.NS", "ticker": "COCHINSHIP", "name": "Cochin Shipyard",             "sector": "Defence Shipbuilding"},
    {"symbol": "GRSE.NS",       "ticker": "GRSE",       "name": "Garden Reach Shipbuilders",   "sector": "Defence Shipbuilding"},
    {"symbol": "BEML.NS",       "ticker": "BEML",       "name": "BEML",                        "sector": "Defence / Railways"},
    {"symbol": "SOLARINDS.NS",  "ticker": "SOLARINDS",  "name": "Solar Industries India",      "sector": "Explosives / Defence"},
    {"symbol": "RAILTEL.NS",    "ticker": "RAILTEL",    "name": "RailTel Corporation",         "sector": "Telecom Infra"},
    {"symbol": "RVNL.NS",       "ticker": "RVNL",       "name": "Rail Vikas Nigam",            "sector": "Railways"},
    {"symbol": "IRCON.NS",      "ticker": "IRCON",      "name": "Ircon International",         "sector": "Railways"},
    {"symbol": "RITES.NS",      "ticker": "RITES",      "name": "RITES",                       "sector": "Railways Consulting"},

    # Capital Goods (small-cap)
    {"symbol": "KIRLOSENG.NS",  "ticker": "KIRLOSENG",  "name": "Kirloskar Oil Engines",       "sector": "Capital Goods"},
    {"symbol": "ELGIEQUIP.NS",  "ticker": "ELGIEQUIP",  "name": "Elgi Equipments",             "sector": "Compressors"},
    {"symbol": "THERMAX.NS",    "ticker": "THERMAX",    "name": "Thermax",                     "sector": "Capital Goods"},
    {"symbol": "KEC.NS",        "ticker": "KEC",        "name": "KEC International",           "sector": "T&D / Infra"},
    {"symbol": "KIRLOSBROS.NS", "ticker": "KIRLOSBROS", "name": "Kirloskar Brothers",          "sector": "Pumps"},

    # Infra / Construction
    {"symbol": "NCC.NS",        "ticker": "NCC",        "name": "NCC",                         "sector": "Infrastructure"},
    {"symbol": "PNCINFRA.NS",   "ticker": "PNCINFRA",   "name": "PNC Infratech",               "sector": "Infrastructure"},
    {"symbol": "GMRINFRA.NS",   "ticker": "GMRINFRA",   "name": "GMR Airports Infrastructure", "sector": "Airports"},

    # Specialty Chemicals & Fertilisers
    {"symbol": "GNFC.NS",       "ticker": "GNFC",       "name": "Gujarat Narmada Valley",      "sector": "Chemicals / Fertilisers"},
    {"symbol": "CHAMBLFERT.NS", "ticker": "CHAMBLFERT", "name": "Chambal Fertilisers",         "sector": "Fertilisers"},
    {"symbol": "FINEORG.NS",    "ticker": "FINEORG",    "name": "Fine Organic Industries",     "sector": "Specialty Chemicals"},
    {"symbol": "CHEMPLAST.NS",  "ticker": "CHEMPLAST",  "name": "Chemplast Sanmar",            "sector": "Chemicals"},

    # Pharma small-caps
    {"symbol": "LAURUSLABS.NS", "ticker": "LAURUSLABS", "name": "Laurus Labs",                 "sector": "Pharma APIs"},
    {"symbol": "NATCOPHARM.NS", "ticker": "NATCOPHARM", "name": "Natco Pharma",                "sector": "Pharma"},
    {"symbol": "AJANTPHARM.NS", "ticker": "AJANTPHARM", "name": "Ajanta Pharma",               "sector": "Pharma"},
    {"symbol": "ERIS.NS",       "ticker": "ERIS",       "name": "Eris Lifesciences",           "sector": "Pharma"},
    {"symbol": "GLAND.NS",      "ticker": "GLAND",      "name": "Gland Pharma",                "sector": "Pharma Injectables"},

    # Diagnostics / Healthcare
    {"symbol": "METROPOLIS.NS", "ticker": "METROPOLIS", "name": "Metropolis Healthcare",       "sector": "Diagnostics"},
    {"symbol": "THYROCARE.NS",  "ticker": "THYROCARE",  "name": "Thyrocare Technologies",      "sector": "Diagnostics"},

    # Consumer / Food / Beverages
    {"symbol": "DEVYANI.NS",    "ticker": "DEVYANI",    "name": "Devyani International",       "sector": "QSR (KFC/Pizza Hut)"},
    {"symbol": "WESTLIFE.NS",   "ticker": "WESTLIFE",   "name": "Westlife Foodworld",          "sector": "QSR (McDonald's)"},
    {"symbol": "KRBL.NS",       "ticker": "KRBL",       "name": "KRBL",                        "sector": "FMCG / Rice"},
    {"symbol": "AVANTIFEED.NS", "ticker": "AVANTIFEED", "name": "Avanti Feeds",                "sector": "Aquaculture"},
    {"symbol": "RADICO.NS",     "ticker": "RADICO",     "name": "Radico Khaitan",              "sector": "Spirits / Liquor"},
    {"symbol": "UNITDSPR.NS",   "ticker": "UNITDSPR",   "name": "United Spirits",              "sector": "Spirits / Liquor"},

    # Sugar
    {"symbol": "EIDPARRY.NS",   "ticker": "EIDPARRY",   "name": "EID Parry India",             "sector": "Sugar"},
    {"symbol": "BALRAMCHIN.NS", "ticker": "BALRAMCHIN", "name": "Balrampur Chini Mills",       "sector": "Sugar"},

    # Steel & Pipes
    {"symbol": "APLAPOLLO.NS",  "ticker": "APLAPOLLO",  "name": "APL Apollo Tubes",            "sector": "Steel Pipes"},
    {"symbol": "RATNAMANI.NS",  "ticker": "RATNAMANI",  "name": "Ratnamani Metals & Tubes",    "sector": "Steel Pipes"},

    # Textiles
    {"symbol": "WELSPUNIND.NS", "ticker": "WELSPUNIND", "name": "Welspun Living",              "sector": "Home Textiles"},
    {"symbol": "PAGEIND.NS",    "ticker": "PAGEIND",    "name": "Page Industries",             "sector": "Innerwear / Apparel"},

    # Banking small-caps
    {"symbol": "RBLBANK.NS",    "ticker": "RBLBANK",    "name": "RBL Bank",                    "sector": "Banking"},
    {"symbol": "INDIANB.NS",    "ticker": "INDIANB",    "name": "Indian Bank",                 "sector": "PSU Banking"},
    {"symbol": "UNIONBANK.NS",  "ticker": "UNIONBANK",  "name": "Union Bank of India",         "sector": "PSU Banking"},

    # Other interesting names
    {"symbol": "PARADEEP.NS",   "ticker": "PARADEEP",   "name": "Paradeep Phosphates",         "sector": "Fertilisers"},
    {"symbol": "ASTRAL.NS",     "ticker": "ASTRAL",     "name": "Astral",                      "sector": "Plastic Pipes"},
    {"symbol": "SUPREMEIND.NS", "ticker": "SUPREMEIND", "name": "Supreme Industries",          "sector": "Plastic Products"},
    {"symbol": "BLUESTARCO.NS", "ticker": "BLUESTARCO", "name": "Blue Star",                   "sector": "Cooling / HVAC"},
    {"symbol": "DIXON.NS",      "ticker": "DIXON",      "name": "Dixon Technologies",          "sector": "Electronics Manufacturing"},
    {"symbol": "AMBER.NS",      "ticker": "AMBER",      "name": "Amber Enterprises",           "sector": "AC OEM"},
]

# Quick assertion so we know if the list size drifts
assert 90 <= len(EXTENDED_UNIVERSE_STOCKS) <= 110, f"Expected ~100 stocks, got {len(EXTENDED_UNIVERSE_STOCKS)}"
