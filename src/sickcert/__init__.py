"""Sick Certificate Data Explorer.

Parses HL7 v2 ORU_R01 messages delivered as XML, flattens each message into
one row per leaf node, and searches those rows by HL7 path spec or free text.
"""

__version__ = "0.1.0"
