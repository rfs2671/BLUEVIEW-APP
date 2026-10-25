import React from 'react';

/**
 * A render error in the tile viewer must never cost the reader their drawing: the
 * boundary reports it and the parent falls back to the PDF viewer for this open.
 */
export default class SheetBoundary extends React.Component {
  constructor(props) { super(props); this.state = { failed: false }; }

  static getDerivedStateFromError() { return { failed: true }; }

  componentDidCatch(error) {
    // eslint-disable-next-line no-console
    console.warn('Tile viewer failed; using the PDF viewer:', error && error.message);
    if (this.props.onFail) this.props.onFail(error);
  }

  render() { return this.state.failed ? null : this.props.children; }
}
