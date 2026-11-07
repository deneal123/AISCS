import React from 'react';
import { Button, Tooltip } from '@chakra-ui/react';

export default function SceneVisibilityControls({
  placing, pickingStimulus, fieldContactPick, nativeView, setNativeView, bodyVisible,
  setBodyVisible, opacity, setOpacity, fullCns, localWindow, setLocalWindow,
  neurons, setNeurons, regionsVisible, setRegionsVisible, electricalPrimary,
  activeField, openElectrodes, busy,
}) {
  return <>
    <Button size="xs" variant="ghost" isDisabled={placing || pickingStimulus || Boolean(fieldContactPick)} onClick={() => {
      setNativeView(false);
      if (!bodyVisible || nativeView) { setBodyVisible(true); setOpacity(1); }
      else if (opacity >= .5) setOpacity(fullCns ? .18 : .24);
      else setBodyVisible(false);
    }}>{!bodyVisible || nativeView ? 'Показать тело' : opacity >= .5 ? 'Сделать тело прозрачным' : 'Убрать тело'}</Button>
    {!fullCns && <Tooltip label="Окно отображения локальной цепи; расчёт не меняется"><Button aria-label="Окно локальной цепи" aria-pressed={localWindow} size="xs" variant={localWindow ? 'outline' : 'ghost'} onClick={() => setLocalWindow(value => !value)}>Окно</Button></Tooltip>}
    <Button size="xs" variant="ghost" aria-pressed={neurons} onClick={() => setNeurons(value => !value)}>{neurons ? 'Скрыть нейроны' : 'Показать нейроны'}</Button>
    {fullCns && <Button size="xs" variant="ghost" aria-pressed={regionsVisible} onClick={() => setRegionsVisible(value => !value)}>{regionsVisible ? 'Скрыть области' : 'Показать области'}</Button>}
    {!fullCns && !electricalPrimary && !activeField && <Tooltip label="E1 и REF регистрируют сигнал и не создают воздействие"><Button size="xs" variant={placing ? 'outline' : 'ghost'} onClick={openElectrodes} isDisabled={busy}>Электроды</Button></Tooltip>}
  </>;
}
