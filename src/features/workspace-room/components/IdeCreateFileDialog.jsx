import { useRef, useState } from 'react';
import { Button, FormControl, FormErrorMessage, FormLabel, Input, Modal, ModalBody, ModalCloseButton, ModalContent, ModalFooter, ModalHeader, ModalOverlay, Text } from '@chakra-ui/react';
import { idePath } from '../model/ideReadContracts';

export default function IdeCreateFileDialog({ operation, onClose, editor }) {
  const [path, setPath] = useState('');
  const [invalid, setInvalid] = useState(false);
  const input = useRef(null);
  const submit = async (event) => {
    event.preventDefault();
    const value = path.trim();
    if (!idePath(value)) { setInvalid(true); input.current?.focus(); return; }
    if (await editor.create(value, operation)) onClose();
  };
  const folder = operation === 'directory';
  return <Modal isOpen onClose={() => { if (!editor.busy) onClose(); }} initialFocusRef={input} isCentered motionPreset="none">
    <ModalOverlay /><ModalContent mx={4} maxW="420px" overflowY="auto">
      <ModalHeader fontSize="md">{folder ? 'Создать папку' : 'Создать файл'}</ModalHeader><ModalCloseButton isDisabled={Boolean(editor.busy)} />
      <form noValidate onSubmit={submit}>
        <ModalBody>
          <FormControl isInvalid={invalid}>
            <FormLabel htmlFor="ide-new-file-path" fontSize="sm">Путь в репозитории</FormLabel>
            <Input ref={input} id="ide-new-file-path" value={path} maxLength={1024} borderRadius="control" placeholder={folder ? 'src' : 'main.py'}
              isReadOnly={Boolean(editor.busy)} onChange={(event) => { setPath(event.target.value); setInvalid(false); }} aria-describedby="ide-create-path-help" />
            {invalid && <FormErrorMessage>Введите относительный путь без «..» и служебных каталогов.</FormErrorMessage>}
          </FormControl>
          <Text id="ide-create-path-help" mt={3} fontSize="xs">Родительская папка должна существовать. Существующие файлы не перезаписываются.</Text>
          {editor.error && <Text role="alert" mt={3} fontSize="sm">{editor.error}</Text>}
        </ModalBody>
        <ModalFooter gap={2}>
          <Button size="document" variant="workbenchSecondary" isDisabled={Boolean(editor.busy)} onClick={onClose}>Отмена</Button>
          <Button type="submit" size="document" variant="workbenchPrimary" isLoading={Boolean(editor.busy)}>Создать</Button>
        </ModalFooter>
      </form>
    </ModalContent>
  </Modal>;
}
