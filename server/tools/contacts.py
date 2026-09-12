from fastmcp import FastMCP

from services.graph import graph_request


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def search_contacts(query: str, limit: int = 25) -> list[dict]:
        """Search contacts by name (matches displayName, givenName, or surname prefix)."""
        escaped = query.replace("'", "''")
        filter_expr = (
            f"startswith(displayName,'{escaped}') or "
            f"startswith(givenName,'{escaped}') or "
            f"startswith(surname,'{escaped}')"
        )
        params = {"$filter": filter_expr, "$top": limit}
        return graph_request("GET", "/me/contacts", params=params).get("value", [])

    @mcp.tool
    def get_contact(contact_id: str) -> dict:
        """Fetch a single contact by id."""
        return graph_request("GET", f"/me/contacts/{contact_id}")

    @mcp.tool
    def create_contact(
        given_name: str,
        surname: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> dict:
        """Create a contact."""
        payload: dict = {"givenName": given_name}
        if surname:
            payload["surname"] = surname
        if email:
            payload["emailAddresses"] = [{"address": email, "name": f"{given_name} {surname or ''}".strip()}]
        if phone:
            payload["mobilePhone"] = phone
        return graph_request("POST", "/me/contacts", json=payload)

    @mcp.tool
    def update_contact(contact_id: str, fields: dict) -> dict:
        """Update a contact. fields may include any Graph contact property
        (e.g. givenName, surname, emailAddresses, mobilePhone).
        """
        return graph_request("PATCH", f"/me/contacts/{contact_id}", json=fields)

    @mcp.tool
    def delete_contact(contact_id: str) -> dict:
        """Delete a contact."""
        graph_request("DELETE", f"/me/contacts/{contact_id}")
        return {"deleted": contact_id}
