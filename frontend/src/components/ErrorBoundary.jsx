import { Component } from 'react'

// Um painel com dados inesperados não derruba a página inteira.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { failed: false }
  }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    if (this.state.failed) {
      return (
        <section className="panel">
          <h2>{this.props.title}</h2>
          <p className="muted">Este painel não conseguiu mostrar os dados.</p>
        </section>
      )
    }
    return this.props.children
  }
}
