import React, { useCallback } from "react";
import { Box, Icon } from "@chakra-ui/react";
import { FiCode, FiFileText, FiGlobe, FiImage, FiPaperclip, FiSearch } from "@shared/icons";
import { colors, motion } from "@theme/tokens";
import { AGENT_META, PLATFORM_SHOWCASE } from "@/content/platform";
import ChatWindow from "./ChatWindow";
import ConversationTurn from "./ConversationTurn";

const ICONS = { FiSearch, FiGlobe, FiImage, FiFileText, FiCode, FiPaperclip };

/**
 * Витрина диалогов: настоящий tablist (роутинг стрелками ←/→, roving tabIndex,
 * подсветка активного агент-цветом) → выбранный диалог поэтапно проигрывается
 * в чат-окне. Контролируется страницей (activeKey/onSelect), чтобы ростер
 * агентов мог открыть нужный пример.
 */
export default function ChatShowcase({ activeKey, onSelect }) {
  const items = PLATFORM_SHOWCASE.conversations;
  const active = items.find((c) => c.key === activeKey) || items[0];
  const meta = AGENT_META[active.agent] || AGENT_META.general;
  const activeIndex = items.findIndex((c) => c.key === active.key);

  const onKeyDown = useCallback(
    (e) => {
      const keys = ["ArrowRight", "ArrowLeft", "Home", "End"];
      if (!keys.includes(e.key)) return;
      e.preventDefault();
      let next = activeIndex;
      if (e.key === "ArrowRight") next = (activeIndex + 1) % items.length;
      else if (e.key === "ArrowLeft") next = (activeIndex - 1 + items.length) % items.length;
      else if (e.key === "Home") next = 0;
      else if (e.key === "End") next = items.length - 1;
      const nextKey = items[next].key;
      onSelect(nextKey);
      requestAnimationFrame(() => {
        const el = document.getElementById(`ptab-${nextKey}`);
        el?.focus();
        // на узком экране лента табов скроллится — подтягиваем выбранный в вид
        el?.scrollIntoView({ block: "nearest", inline: "nearest" });
      });
    },
    [activeIndex, items, onSelect],
  );

  return (
    <Box>
      <Box
        role="tablist"
        aria-label="Примеры работы агентов"
        aria-orientation="horizontal"
        onKeyDown={onKeyDown}
        display="flex"
        gap={2}
        justifyContent={{ base: "flex-start", md: "center" }}
        overflowX="auto"
        pb={2}
        mb={{ base: 5, md: 7 }}
        sx={{
          scrollbarWidth: "none",
          "&::-webkit-scrollbar": { display: "none" },
          // На узком экране 6 табов не помещаются: скроллбар скрыт, и последний
          // таб просто обрывался у края — было не понять, что лента прокручивается.
          // Фейд у правого края показывает продолжение (на десктопе всё влезает).
          "@media (max-width: 767px)": {
            maskImage: "linear-gradient(90deg, #000 calc(100% - 36px), transparent 100%)",
            WebkitMaskImage: "linear-gradient(90deg, #000 calc(100% - 36px), transparent 100%)",
          },
        }}
      >
        {items.map((conv) => {
          const m = AGENT_META[conv.agent] || AGENT_META.general;
          const TabIcon = ICONS[conv.icon] || FiSearch;
          const isActive = conv.key === active.key;
          return (
            <Box
              as="button"
              key={conv.key}
              id={`ptab-${conv.key}`}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-controls="platform-tabpanel"
              tabIndex={isActive ? 0 : -1}
              onClick={() => onSelect(conv.key)}
              flexShrink={0}
              display="inline-flex"
              alignItems="center"
              gap={2}
              px={3.5}
              py={2}
              borderRadius="full"
              fontSize="13px"
              fontWeight="600"
              whiteSpace="nowrap"
              transition={`color 180ms ${motion.easeOut}, background 220ms ${motion.easeOut}, border-color 220ms ${motion.easeOut}, box-shadow 220ms ${motion.easeOut}`}
              color={isActive ? colors.fg[1] : colors.fg[3]}
              bg={isActive ? `${m.color}22` : colors.surface.tint2}
              border={`1px solid ${isActive ? `${m.color}88` : colors.border.subtle}`}
              boxShadow={isActive ? `0 0 16px ${m.color}33` : "none"}
              _hover={{ color: colors.fg[1], borderColor: `${m.color}66`, bg: `${m.color}18` }}
              _focusVisible={{ outline: "none", boxShadow: `0 0 0 2px ${m.color}66` }}
            >
              <Icon as={TabIcon} boxSize="14px" color={isActive ? m.color : "currentColor"} />
              {conv.tab}
            </Box>
          );
        })}
      </Box>

      <Box maxW="900px" mx="auto">
        <ChatWindow title={`GPTHub · ${meta.label}`}>
          <Box id="platform-tabpanel" role="tabpanel" tabIndex={0} aria-labelledby={`ptab-${active.key}`}>
            <ConversationTurn key={active.key} conversation={active} />
          </Box>
        </ChatWindow>
      </Box>
    </Box>
  );
}
