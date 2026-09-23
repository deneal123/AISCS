import React from "react";
import { HStack, Text, VStack } from "@chakra-ui/react";
import Logo from "@shared/ui/assets/common/Logo";
import { colors } from "@theme/tokens";

import { PROJECT_NAME } from "@constants";

function BrandMark({ size = "md", showSubtitle = true, iconOnly = false }) {
  const iconSize = size === "sm" ? "28px" : "34px";

  if (iconOnly) {
    return <Logo boxSize={iconSize} />;
  }

  return (
    <HStack spacing={3} align="center">
      <Logo boxSize={iconSize} />
      <VStack spacing={0} align="flex-start">
        <Text fontSize={size === "sm" ? "lg" : "xl"} fontWeight="600" color={colors.text.primary} lineHeight="1">
          {PROJECT_NAME}
        </Text>
        {showSubtitle && (
          <Text
            fontSize="9px"
            letterSpacing="0.16em"
            textTransform="uppercase"
            color={colors.text.tertiary}
          >
            AI Workspace
          </Text>
        )}
      </VStack>
    </HStack>
  );
}

export default BrandMark;
