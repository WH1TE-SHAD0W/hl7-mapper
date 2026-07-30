"""HL7 Message Data Explorer.

Parses HL7 v2 messages delivered as XML -- ORU_R01, REF_I12, ORM_O01 and any
structurally similar type -- flattens each into one row per leaf node, and
searches those rows by HL7 path spec or free text.
"""

__version__ = "0.1.0"
