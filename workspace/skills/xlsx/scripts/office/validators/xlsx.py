"""
Validator for Excel workbook XML files against XSD schemas.
"""

from .base import BaseSchemaValidator


class XLSXSchemaValidator(BaseSchemaValidator):

    ELEMENT_RELATIONSHIP_TYPES = {
        "sheet": "worksheet",
    }

    def validate(self):
        if not self.validate_xml():
            return False

        all_valid = True
        if not self.validate_namespaces():
            all_valid = False

        if not self.validate_unique_ids():
            all_valid = False

        if not self.validate_file_references():
            all_valid = False

        if not self.validate_content_types():
            all_valid = False

        if not self.validate_against_xsd():
            all_valid = False

        if not self.validate_all_relationship_ids():
            all_valid = False

        return all_valid


if __name__ == "__main__":
    raise RuntimeError("This module should not be run directly.")
