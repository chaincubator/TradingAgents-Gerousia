from flask import Flask, jsonify
import sys
import os
import secrets

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['DEBUG'] = False

@app.route('/')
def index():
    return jsonify({
        'message': 'Trading Agents Crypto - Vercel Demo',
        'status': 'running',
        'environment': 'vercel',
        'version': '1.0.0-test'
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'message': 'Application is running successfully on Vercel'
    })

@app.route('/api/info')
def api_info():
    return jsonify({
        'name': 'Trading Agents Crypto',
        'environment': 'Vercel Serverless',
        'mode': 'Demo/Test',
        'limitations': [
            'No real-time analysis (SocketIO not supported)',
            'Limited execution time (5 minutes)',
            'No persistent storage',
            'Simplified functionality'
        ]
    })

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# This is what Vercel expects
def handler(event, context):
    return app(event, context)

# Export the app
vercel_app = app

if __name__ == '__main__':
    app.run(debug=True) 