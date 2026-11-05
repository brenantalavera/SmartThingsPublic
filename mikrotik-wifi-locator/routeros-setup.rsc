# Run on the MikroTik (Terminal in WinBox/WebFig, or `/import routeros-setup.rsc`).
# Creates a READ-ONLY account for the locator and enables the API it uses.
# Replace 192.168.88.0/24 with the subnet the locator computer is on, and pick a real password.

# On RouterOS 6, remove ",rest-api" from the next line.
/user group add name=locator policy=read,api,rest-api
/user add name=locator group=locator password="change-me" address=192.168.88.0/24

# --- RouterOS 7, REST over HTTPS (recommended) ---
# Needs a certificate on www-ssl. A self-signed one is fine:
/certificate add name=locator-https common-name=router days-valid=3650 key-usage=digital-signature,key-encipherment,tls-server
/certificate sign locator-https
/ip service set www-ssl certificate=locator-https disabled=no address=192.168.88.0/24

# --- OR: REST over plain HTTP (simpler; set https=false in config.toml) ---
# /ip service set www disabled=no address=192.168.88.0/24

# --- OR: RouterOS 6 / classic API (mode="api" in config.toml) ---
# /ip service set api disabled=no address=192.168.88.0/24

# Optional but recommended: give each phone a friendly name via its DHCP lease comment
# /ip dhcp-server lease set [find mac-address=12:34:56:78:9A:BC] comment="Brenan's phone"
