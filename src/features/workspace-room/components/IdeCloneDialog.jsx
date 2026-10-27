import { useRef, useState } from 'react';
import { Button, FormControl, FormErrorMessage, FormLabel, Input, Modal, ModalBody, ModalCloseButton, ModalContent, ModalFooter, ModalHeader, ModalOverlay, Text } from '@chakra-ui/react';

export default function IdeCloneDialog({ git, isolated, onClose }) {
  const [origin, setOrigin] = useState(isolated?.request?.origin || '');
  const [branch, setBranch] = useState(isolated?.request?.branch || '');
  const [invalid, setInvalid] = useState(false);
  const input = useRef(null);
  const busy = Boolean(git.busy || isolated?.busy);
  const locked = Boolean(isolated?.locked);
  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    if (!/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/?$/.test(origin.trim())) { setInvalid(true); input.current?.focus(); return; }
    const values = { origin: origin.trim(), branch: branch.trim() };
    if (await (locked ? isolated.run(values) : git.run('clone', values))) onClose();
  };
  return <Modal isOpen initialFocusRef={input} onClose={() => { if (!busy) onClose(); }} isCentered motionPreset="none" scrollBehavior="inside">
    <ModalOverlay /><ModalContent mx={4} maxW="440px" overflow="hidden">
      <ModalHeader fontSize="md">Клонировать репозиторий</ModalHeader><ModalCloseButton aria-label="Закрыть клонирование" isDisabled={busy} />
      <form noValidate onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}><ModalBody>
        <FormControl isInvalid={invalid} mb={3}>
          <FormLabel htmlFor="ide-clone-origin" fontSize="sm">Ссылка на репозиторий</FormLabel>
          <Input id="ide-clone-origin" ref={input} value={origin} maxLength={512} placeholder="https://github.com/owner/repository" isReadOnly={busy || locked}
            aria-describedby={invalid ? 'ide-clone-error' : 'ide-clone-help'} onChange={event => { setOrigin(event.target.value); setInvalid(false); }} />
          {invalid && <FormErrorMessage id="ide-clone-error">Нужна HTTPS-ссылка на репозиторий GitHub, без токена и параметров.</FormErrorMessage>}
        </FormControl>
        <FormControl><FormLabel htmlFor="ide-clone-branch" fontSize="sm">Ветка (необязательно)</FormLabel>
          <Input id="ide-clone-branch" value={branch} maxLength={200} placeholder="Основная ветка репозитория" isReadOnly={busy || locked} onChange={event => setBranch(event.target.value)} />
        </FormControl>
        <Text id="ide-clone-help" mt={3} fontSize="xs">Публичный GitHub, до 20 МБ Git-объектов. Нетронутая автозаготовка будет заменена; если в проекте уже есть данные, клон получит отдельную среду. Текущие файлы сохранятся. Скрипты и подмодули не запускаются.</Text>
        {(isolated?.error || git.error) && <Text role={isolated?.error && ['preparing', 'running', 'complete'].includes(isolated?.result?.state) ? 'status' : 'alert'} mt={3} fontSize="sm">{isolated?.error || git.error}</Text>}
        {isolated?.result && <Button mt={2} size="document" variant="workbenchSecondary" isDisabled={busy} onClick={isolated.open}>Открыть созданный проект</Button>}
      </ModalBody><ModalFooter gap={2}>
        <Button size="document" variant="workbenchSecondary" onClick={onClose} isDisabled={busy}>Отмена</Button>
        <Button type="submit" size="document" variant="workbenchPrimary" isLoading={busy}>{locked ? isolated?.result?.state === 'complete' ? 'Открыть клон' : ['preparing', 'blocked'].includes(isolated?.result?.state) ? 'Продолжить попытку' : 'Проверить результат' : 'Клонировать'}</Button>
      </ModalFooter></form>
    </ModalContent>
  </Modal>;
}
