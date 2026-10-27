import React, { forwardRef } from 'react';
import { Text, useMergeRefs } from '@chakra-ui/react';
import { components } from 'react-select';
import ChoiceHint from '../ChoiceHint';

// Tooltip описывает сам option, не создавая generic ARIA-узел внутри listbox.
const HintOption = forwardRef(function HintOption({ optionProps, ...triggerProps }, forwardedRef) {
  const innerRef = useMergeRefs(optionProps.innerRef, forwardedRef);
  const innerProps = { ...optionProps.innerProps, ...triggerProps };
  for (const key of Object.keys(triggerProps)) {
    if (/^on[A-Z]/.test(key) && typeof optionProps.innerProps[key] === 'function'
      && typeof triggerProps[key] === 'function') {
      innerProps[key] = event => {
        optionProps.innerProps[key](event);
        triggerProps[key](event);
      };
    }
  }
  return <components.Option {...optionProps} innerProps={innerProps} innerRef={innerRef} />;
});

export default function ComposerOption(props) {
  const optionProps = { ...props, innerProps: { ...props.innerProps,
    ...(props.data.invitation && !props.isSelected && !props.isFocused && !props.isDisabled
      ? { 'data-choice-local-invitation': 'true' } : {}),
    ...(props.selectProps.iconPalette ? { 'aria-label': props.label } : {}) } };
  const hint = props.selectProps.getOptionHint?.(props.data)
    || (props.selectProps.iconPalette ? props.data.hint : null);
  if (!props.selectProps.iconPalette && !hint) return <components.Option {...optionProps} />;
  return <ChoiceHint keyboardOpen={props.isFocused && props.selectProps.showOptionHints}
    label={<><Text fontSize="12px" fontWeight={600}>{props.label}</Text><Text fontSize="12px">{hint}</Text></>}
    renderTrigger={triggerProps => <HintOption optionProps={optionProps} {...triggerProps} />} />;
}
