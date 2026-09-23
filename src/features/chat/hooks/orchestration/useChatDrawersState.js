import { useDisclosure } from '@chakra-ui/react';
import { useState } from 'react';

export function useChatDrawersState(profileDisclosure) {
  const sidebarDisclosure = useDisclosure();
  const memoryDisclosure = useDisclosure();
  const graphDisclosure = useDisclosure();
  // Рабочее место треда: дерево файлов песочницы, превью и история правок. Отдельной
  // панелью, а не в ленте: дерево на тысячу файлов не должно ехать с каждым ответом.
  // Обзор файлов аккаунта — ОТДЕЛЬНОЕ окно: рабочий каталог временный и привязан к
  // треду, а этот список накопительный и общий для всех чатов.
  const settingsDisclosure = useDisclosure();
  const [memoryFacts, setMemoryFacts] = useState([]);
  // Дашборд семантической памяти MemOS (объём по типам узлов). null — не загружен
  // / провайдер не memos. Вторичен к memoryFacts, обновляется при открытии панели.
  const [memoryDashboard, setMemoryDashboard] = useState(null);

  return {
    state: {
      sidebarDisclosure,
      memoryDisclosure,
      graphDisclosure,
      settingsDisclosure,
      profileDisclosure,
      memoryFacts,
      memoryDashboard,
    },
    actions: {
      setMemoryFacts,
      setMemoryDashboard,
    },
  };
}
