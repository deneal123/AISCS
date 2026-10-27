import { FiActivity, FiBarChart2, FiCompass, FiSearch, FiTool, FiUser, FiUsers } from '@shared/icons';

// Product-owned outline glyphs: one identity on onboarding cards and in pickers.
// Admin-defined personalities remain usable without a frontend release.
const PERSONA_ICONS = {
  analyst: FiBarChart2,
  engineer: FiTool,
  psychologist: FiUsers,
  financier: FiActivity,
  scientist: FiSearch,
  tarot: FiCompass,
};

export const getPersonaIcon = id => Object.hasOwn(PERSONA_ICONS, id) ? PERSONA_ICONS[id] : FiUser;
