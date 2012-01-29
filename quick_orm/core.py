# coding=utf-8
"""
    quick_orm.core
    ~~~~~~~~~~~~~~
    Core of Quick ORM
"""
from toolkit_library.string_util import StringUtil
from sqlalchemy import create_engine, Column, Integer, ForeignKey, String
from sqlalchemy.orm import scoped_session, sessionmaker, relationship, backref
from sqlalchemy.schema import Table
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta, _as_declarative
from extensions import DatabaseExtension, SessionExtension

models = list()

class MyDeclarativeMeta(DeclarativeMeta):
    #override __init__ of DeclarativeMeta
    def __init__(cls, classname, bases, attrs):
        models.append(cls)
        return type.__init__(cls, classname, bases, attrs)


@DatabaseExtension.extend # extend Database to add some useful methods
class Database(object):
    """Represent a connection to a specific database"""

    Base = declarative_base() 

    @staticmethod
    def register():
        for i in range(len(models)):
            model = models[i]
            if '_decl_class_registry' in model.__dict__:
                continue
            _as_declarative(model, model.__name__, model.__dict__)

            # for ref grandchildren
            for j in range(i):
                if not models[j] in model.__bases__:
                    continue
                parent = models[j]
               # if hasattr(parent, '_one_to_one_models'):
               #     for grandparent in getattr(parent, '_one_to_one_models'):
                        
                for k in range(j):
                    if not hasattr(parent, StringUtil.camelcase_to_underscore(models[k].__name__)):
                        continue
                    grandparent = models[k]
                    setattr(grandparent, StringUtil.camelcase_to_underscore(model.__name__) + 's', 
                            (lambda parent, model: property(lambda self: getattr(self, StringUtil.camelcase_to_underscore(parent.__name__) + 's')
                            .filter_by(real_type = StringUtil.camelcase_to_underscore(model.__name__))))(parent, model))

        models[:] = []

    def __init__(self, connection_string):
        """Initiate a database engine which is very low level, and a database session which deals with orm."""

        # Solve an issue with mysql character encoding(maybe it's a bug of MySQLdb)
        # Refer to http://plone.293351.n2.nabble.com/Troubles-with-encoding-SQLAlchemy-MySQLdb-or-mysql-configuration-pb-td4827540.html
        if 'mysql:' in connection_string and 'charset=' not in connection_string:
            raise ValueError("""No charset was specified for a mysql connection string. 
Please specify something like '?charset=utf8' explicitly.""")

        self.engine = create_engine(connection_string, convert_unicode = True, encoding = 'utf-8')
        self.session = scoped_session(sessionmaker(autocommit = False, autoflush = False, bind = self.engine))        
        self.session = SessionExtension.extend(self.session) # extend session to add some shortcut methods    

    @staticmethod
    def foreign_key(ref_model, ref_name = None, backref_name = None, one_to_one = False):
        """"Class decorator, add a foreign key to a SQLAlchemy model.
        Parameters:
            ref_model is the destination model, in a one-to-many relationship, it is the "one" side.
            ref_name is the user-friendly name of destination model(if omitted, destintion table name will be used instead).
            backref_name is the name used to back ref the "many" side.
            one_to_one is this foreign_key for a one-to-one relationship?
        """
        if isinstance(ref_model, str):
            ref_model_name = ref_model
        else:
            ref_model_name = ref_model.__name__
        ref_table_name = StringUtil.camelcase_to_underscore(ref_model_name)
        ref_name = ref_name or ref_table_name
        foreign_key = '{0}_id'.format(ref_name)        
        def ref_table(cls):
            if not isinstance(ref_model, str):
                foreign_key_attr = '_one_to_one_models' if one_to_one else '_many_to_one_models'
                if not hasattr(cls, foreign_key_attr):
                    setattr(cls, foreign_key_attr, [ref_model, ])
                else:
                    getattr(cls, foreign_key_attr).append(ref_model)
            model_name = cls.__name__
            table_name = StringUtil.camelcase_to_underscore(model_name)
            setattr(cls, foreign_key, Column(Integer, ForeignKey('{0}.id'.format(ref_table_name), ondelete = "CASCADE")))
            my_backref_name = backref_name or (table_name if one_to_one else '{0}s'.format(table_name))
            backref_options = dict(uselist = False) if one_to_one else dict(lazy = 'dynamic')
            backref_options['cascade'] = 'all'
            setattr(cls, ref_name, relationship(ref_model_name, 
                primaryjoin = '{0}.{1} == {2}.id'.format(model_name, foreign_key, ref_model_name), 
                backref = backref(my_backref_name, **backref_options), remote_side = '{0}.id'.format(ref_model_name)))
            return cls
        return ref_table


    @staticmethod
    def many_to_many(ref_model, ref_name = None, backref_name = None, middle_table_name = None):
        """Class Decorator, add a many-to-many relationship between two SQLAlchemy models.
        Parameters:
            ref_table_name is the name of the destination table, it is NOT the one decorated by this method.
            ref_name is how this model reference the destination models.
            backref_name is how the destination model reference this model.
            middle_table_name is the middle table name of this many-to-many relationship.
        """
        if isinstance(ref_model, str):
            ref_model_name = ref_model
        else:
            ref_model_name = ref_model.__name__
        ref_table_name = StringUtil.camelcase_to_underscore(ref_model_name)
        ref_name = ref_name or '{0}s'.format(ref_table_name)
        def ref_table(cls):
            if not isinstance(ref_model, str):
                if not hasattr(cls, '_many_to_many_models'):
                    setattr(cls, '_many_to_many_models', [ref_model, ])
                else:
                    getattr(cls, '_many_to_many_models').append(ref_model)
            table_name = StringUtil.camelcase_to_underscore(cls.__name__)
            my_middle_table_name = middle_table_name or '{0}_{1}'.format(table_name, ref_table_name)

            if table_name == ref_table_name:
                left_column_name = 'left_id'
                right_column_name = 'right_id'                
            else:
                left_column_name = '{0}_id'.format(table_name)
                right_column_name = '{0}_id'.format(ref_table_name)           

            middle_table = Table(my_middle_table_name, Database.Base.metadata,
                Column(left_column_name, Integer, ForeignKey('{0}.id'.format(table_name), ondelete = "CASCADE"), primary_key = True),
                Column(right_column_name, Integer, ForeignKey('{0}.id'.format(ref_table_name), ondelete = "CASCADE"), primary_key = True))

            my_backref_name = backref_name or '{0}s'.format(table_name)
            parameters = dict(secondary = middle_table, lazy = 'dynamic', backref = backref(my_backref_name, lazy = 'dynamic'))
            if table_name == ref_table_name:             
                parameters['primaryjoin'] = cls.id == middle_table.c.left_id
                parameters['secondaryjoin'] = cls.id == middle_table.c.right_id

            setattr(cls, ref_name, relationship(ref_model_name, **parameters))

            return cls
        return ref_table


    class DefaultMeta(MyDeclarativeMeta):
        """metaclass for all model classes, let model class inherit Database.Base and handle table inheritance.
        All other model metaclasses are either directly or indirectly derived from this class.
        """
        def __new__(cls, name, bases, attrs):
            # add Database.Base as parent class
            bases = list(bases)
            if object in bases: 
                bases.remove(object)
            bases.append(Database.Base)
            seen = set()
            bases = tuple(base for base in bases if not base in seen and not seen.add(base))
            
            attrs['__tablename__'] = StringUtil.camelcase_to_underscore(name)
            attrs['id'] = Column(Integer, primary_key = True)

            # the for loop bellow handles table inheritance
            for base in [base for base in bases if base in models]:
                if not hasattr(base, 'real_type'):
                    base.real_type = Column('real_type', String(24), nullable = False, index = True)
                    if hasattr(base, '__mapper_args__'):
                        base.__mapper_args__['polymorphic_on'] = base.real_type
                        base.__mapper_args__['polymorphic_identity'] = StringUtil.camelcase_to_underscore(base.__name__)
                    else:
                        base.__mapper_args__ = {'polymorphic_on': base.real_type, 'polymorphic_identity': StringUtil.camelcase_to_underscore(base.__name__)}
                attrs['id'] = Column(Integer, ForeignKey('{0}.id'.format(StringUtil.camelcase_to_underscore(base.__name__)), ondelete = "CASCADE"), primary_key = True)
                if '__mapper_args__' in attrs:
                    attrs['__mapper_args__']['polymorphic_identity'] = StringUtil.camelcase_to_underscore(name)
                    attrs['__mapper_args__']['inherit_condition'] = attrs['id'] == base.id
                else:
                    attrs['__mapper_args__'] = {'polymorphic_identity': StringUtil.camelcase_to_underscore(name), 'inherit_condition': attrs['id'] == base.id}          
                    
            return MyDeclarativeMeta.__new__(cls, name, bases, attrs)  
    

    @staticmethod
    def MetaBuilder(*models):
        """Build a new model metaclass. The new metaclass is derived from Database.DefaultMeta,
        and it will add *models as base classes to a model class.
        """
        class InnerMeta(Database.DefaultMeta):
            """metaclass for model class, it will add *models as bases of the model class."""
            def __new__(cls, name, bases, attrs):
                bases = list(bases)
                for model in models:
                    bases.append(model)
                seen = set()
                bases = tuple(base for base in bases if not base in seen and not seen.add(base))
                return Database.DefaultMeta.__new__(cls, name, bases, attrs)
        return InnerMeta
