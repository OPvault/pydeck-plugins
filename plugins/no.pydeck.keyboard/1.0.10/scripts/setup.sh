#!/bin/bash
# Post-install: ensure the current user belongs to the 'input' group
# so the keyboard plugin can access /dev/uinput and /dev/input/*.

USER_NAME="${SUDO_USER:-$USER}"

if id -nG "$USER_NAME" | grep -qw input; then
    echo "User '$USER_NAME' is already in the 'input' group."
    exit 0
fi

echo "Adding '$USER_NAME' to the 'input' group..."
usermod -aG input "$USER_NAME"

# Apply the new group to the current process so the plugin works
# immediately without requiring a full logout/login.
newgrp input

echo "Done. User '$USER_NAME' has been added to the 'input' group."
