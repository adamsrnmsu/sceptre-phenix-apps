package main

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/mitchellh/mapstructure"

	"phenix-apps/util"
)

// ovsTokenRegex matches a single safe token for interpolation into ovs-vsctl
// commands run on cluster hosts (bridge names, VLAN aliases, interface names).
var ovsTokenRegex = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,15}$`)

// validateOVSToken ensures a metadata-provided value is a single, safe token
// before it gets interpolated into an ovs-vsctl command. It explicitly rejects
// whitespace and the `--` command separator on top of the allowlist regex.
func validateOVSToken(field, value string) error {
	if value == "--" || strings.ContainsAny(value, " \t\r\n") || !ovsTokenRegex.MatchString(value) {
		return fmt.Errorf(
			"invalid %s %q in mirror app metadata: must match %s and must not be `--`",
			field,
			value,
			ovsTokenRegex,
		)
	}

	return nil
}

func extractMetadata(data map[string]any) (MirrorAppMetadataV1, error) {
	var (
		amd     MirrorAppMetadataV1
		version = util.ExtractVersion(data)
	)

	switch version {
	case "v0":
		var md MirrorAppMetadata

		err := mapstructure.Decode(data, &md)
		if err != nil {
			return amd, fmt.Errorf("decoding app metadata: %w", err)
		}

		amd.Upgrade(md)
	case "v1":
		err := mapstructure.Decode(data, &amd)
		if err != nil {
			return amd, fmt.Errorf("decoding app metadata: %w", err)
		}
	}

	// Empty values are allowed here: defaults are applied after decoding (the
	// experiment default bridge and the `mirror` VLAN alias).
	if amd.MirrorBridge != "" {
		err := validateOVSToken("mirrorBridge", amd.MirrorBridge)
		if err != nil {
			return amd, err
		}
	}

	if amd.MirrorVLAN != "" {
		err := validateOVSToken("mirrorVLAN", amd.MirrorVLAN)
		if err != nil {
			return amd, err
		}
	}

	return amd, nil
}

func extractHostMetadata(data map[string]any) (MirrorHostMetadata, error) {
	var (
		hmd     MirrorHostMetadata
		version = util.ExtractVersion(data)
	)

	//nolint:gocritic // switch for future versions
	switch version {
	case "v0":
		err := mapstructure.Decode(data, &hmd)
		if err != nil {
			return hmd, fmt.Errorf("decoding host metadata: %w", err)
		}
	}

	for _, hil := range hmd.HIL {
		err := validateOVSToken("hilInterfaces entry", hil)
		if err != nil {
			return hmd, err
		}
	}

	return hmd, nil
}
