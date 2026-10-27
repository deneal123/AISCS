import { useRef, useState } from 'react';
import { Button, FormControl, FormErrorMessage, FormLabel, Input, Modal, ModalBody, ModalCloseButton, ModalContent, ModalFooter, ModalHeader, ModalOverlay, Text } from '@chakra-ui/react';
import AppSelect from '@shared/controls/AppSelect';
import { idePath } from '../model/ideReadContracts';

export default function IdeMoveFileDialog({ file, tree, editor, onClose }) {
  const [folder, setFolder] = useState(file.path.split('/').slice(0, -1).join('/'));
  const [name, setName] = useState(file.path.split('/').pop());
  const [invalid, setInvalid] = useState(false);
  const input = useRef(null);
  const busy = Boolean(editor.busy);
  const directory = file.type === 'dir';
  const options = [{ value: '', label: 'Корень репозитория' }, ...tree.entries.filter(item => item.type === 'dir' && item.path !== file.path && !item.path.startsWith(`${file.path}/`)).map(item => ({ value: item.path, label: item.path }))];
  const submit = async event => {
    event.preventDefault();
    const destination = [folder, name.trim()].filter(Boolean).join('/');
    if (!name.trim() || name.includes('/') || !idePath(destination) || destination === file.path || destination.startsWith(`${file.path}/`)) { setInvalid(true); input.current?.focus(); return; }
    if (await editor.move(file, destination)) onClose();
  };
  return <Modal isOpen initialFocusRef={input} onClose={() => { if (!busy) onClose(); }} isCentered motionPreset="none">
    <ModalOverlay /><ModalContent mx={4} maxW="440px" overflowY="auto">
      <ModalHeader fontSize="md">{directory ? 'Переместить папку' : 'Переместить файл'}</ModalHeader><ModalCloseButton isDisabled={busy} />
      <form noValidate onSubmit={submit}><ModalBody>
        <Text fontSize="xs" mb={3} overflowWrap="anywhere">Из: {file.path}</Text>
        <FormControl mb={3}><FormLabel htmlFor="ide-move-folder" fontSize="sm">Папка назначения</FormLabel>
          <AppSelect inputId="ide-move-folder" ariaLabel="Папка назначения" size="document" value={folder} options={options}
            isDisabled={busy} menuPortalTarget={null} onChange={value => { setFolder(value); setInvalid(false); }} />
        </FormControl>
        <FormControl isInvalid={invalid}><FormLabel htmlFor="ide-move-name" fontSize="sm">{directory ? 'Имя папки' : 'Имя файла'}</FormLabel>
          <Input id="ide-move-name" ref={input} value={name} maxLength={255} isReadOnly={busy} onChange={event => { setName(event.target.value); setInvalid(false); }} aria-describedby="ide-move-help" />
          {invalid && <FormErrorMessage>Укажите другое расположение и допустимое имя без «/».</FormErrorMessage>}
        </FormControl>
        <Text id="ide-move-help" mt={3} fontSize="xs">{directory ? 'Папка переместится вместе с содержимым.' : 'Содержимое файла сохранится.'} Существующий путь не заменяется.</Text>
        {tree.truncated && <Text mt={2} fontSize="xs">Показаны только загруженные папки дерева.</Text>}
        {editor.error && <Text role="alert" mt={3} fontSize="sm">{editor.error}</Text>}
      </ModalBody><ModalFooter gap={2}>
        <Button size="document" variant="workbenchSecondary" isDisabled={busy} onClick={onClose}>Отмена</Button>
        <Button size="document" type="submit" variant="workbenchPrimary" isLoading={busy}>Переместить</Button>
      </ModalFooter></form>
    </ModalContent>
  </Modal>;
}
