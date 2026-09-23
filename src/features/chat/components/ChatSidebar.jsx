import React from 'react';
import { Box } from '@chakra-ui/react';
import { CHAT_THEME } from '../constants/theme';

function ChatSidebar({ isCollapsed, inDrawer = false, children }) {
  // Внутри мобильного Drawer — всегда во всю ширину/высоту и без адаптивного
  // display:none (иначе тот же адаптив скрывал бы контент дровера → пустой дровер).
  if (inDrawer) {
    return (
      <Box as="aside" display="flex" flexDirection="column" w="full" h="full" overflow="hidden">
        {children}
      </Box>
    );
  }
  return (
    <Box
      as="aside"
      display={{ base: 'none', lg: 'flex' }}
      flexDirection="column"
      w={isCollapsed ? '0' : '272px'}
      minW={isCollapsed ? '0' : '272px'}
      overflow="hidden"
      borderRight={isCollapsed ? 'none' : '1px solid'}
      borderColor={CHAT_THEME.panelBorder}
      transition="all 0.24s cubic-bezier(0.4,0,0.2,1)"
    >
      {!isCollapsed && children}
    </Box>
  );
}

export default ChatSidebar;
