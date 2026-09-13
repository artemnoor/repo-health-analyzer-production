# frozen_string_literal: true
$:.push File.expand_path('lib', __dir__)

# Maintain your gem's version:
require 'random/auth/version'

# Describe your gem and declare its dependencies:
Gem::Specification.new do |s|
  s.name        = 'random'
  s.version     = Random::Auth::VERSION
  s.authors     = ['random Team']
  s.email       = ['dev@random.com']
  s.summary     = 'random'
  s.license     = 'random'

  s.files = Dir['{app,config,db,lib}/**/*', 'LICENSE', 'Rakefile', 'README.md']
  s.test_files = Dir['spec/**/*']

  s.add_dependency 'activerecord-session_store'
  s.add_dependency 'attr_encrypted'
  s.add_dependency 'rails', '~> 6.1'

  s.add_development_dependency 'bundler'
  s.add_development_dependency 'randomplugin', '0.1.0'
  s.add_development_dependency 'package-file-gemfile', '0.1.0'
  s.add_development_dependency 'package-file-gemfile1', '~> 0.1.0'
  s.add_development_dependency 'rubyplugin3', '0.1.0'
  s.metadata = {
    'rubygems_mfa_required' => 'true'
  }
end
