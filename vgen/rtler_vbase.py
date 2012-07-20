"""Base modeling components for constructing hardware description models.

This module contains a collection of classes that can be used to construct MTL
(pronounced metal) models. Once constructed, a MTL model can be leveraged by
a number of tools for various purposes (simulation, translation into HDLs, etc).
"""

class ValueNode(object):

  """Hidden class implementing a node storing value (like a net in Verilog).

  Connected ports and wires have a pointer to the same ValueNode
  instance, such that reads and writes remain consistent.
  """

  # TODO: move ValueNode to rtler_simulate.py?
  # TODO: handle X values
  #def __init__(self, width, value='X'):
  def __init__(self, width, value=0, sim=None):
    """Constructor for a ValueNode object.

    Parameters
    ----------
    width: bitwidth of the node.
    value: initial value of the node. Only set by Constant objects.
    sim: simulation object to register events with on write. (TODO)
    """
    self.sim = sim
    self.width = width
    self._value = value

  @property
  def value(self):
    """Value stored by node. Informs the attached simulator on any write."""
    return self._value
  @value.setter
  def value(self, value):
    # TODO: debug_reg_eventqueue
    #print "    VALUE:", self, bin(value)
    # TODO: nodes not in the vnode_callback list dont have a sim object! Fix!
    if self.sim: self.sim.add_event(self)
    else:        print "// warning: writing a node with no simulator pointer!"
    self._value = value


class VerilogSlice(object):

  """Hidden class implementing the ability to access sub-bits of a wire/port.

  This class automatically handles reading and writing the correct subset of
  bits in a ValueNode.  The VerilogSlice has been designed to be as
  transparent as possible so that logic generally does not have to behave
  differently when accessing a VerilogSlice vs. a Verilog Port.
  """

  def __init__(self, parent_ptr, width, addr):
    """Constructor for a VerilogSlice object.

    Parameters
    ----------
    parent_ptr: the port/wire instance we are slicing.
    width: number of bits we are slicing.
    addr: address range of bits we are slicing, either an int or slice object.
    """
    self.parent_ptr = parent_ptr
    self.width      = width
    self.addr       = addr

  @property
  def parent(self):
    """Return the parent of the port/wire we are slicing."""
    return self.parent_ptr.parent

  @property
  def name(self):
    """Return the name and bitrange of the port/wire we are slicing."""
    suffix = '[%d]' % self.addr
    return self.parent_ptr.name + suffix

  #TODO: hacky...
  @property
  def type(self):
    """Return the type of object we are slicing."""
    return self.parent_ptr.type

  @property
  def connections(self):
    """The list of connections attached to the port/wire we are slicing."""
    return self.parent_ptr.connections
  @connections.setter
  def connections(self, target):
    self.parent_ptr.connections += [target]

  @property
  def value(self):
    """Value of the bits we are slicing."""
    temp = ((self.parent_ptr.value) & (1 << self.addr)) >> self.addr
    return temp
  @value.setter
  def value(self, value):
    self.parent_ptr.value |= (value << self.addr)

  @property
  def _value(self):
    """The ValueNode pointed to by the port/wire we are slicing."""
    return self.parent_ptr._value
  @_value.setter
  def _value(self, value):
    self.parent_ptr._value = value


class VerilogPort(object):

  """Hidden base class implementing a module port."""

  def __init__(self, type=None, width=None, name='???', str=None):
    """Constructor for a VerilogPort object.

    Parameters
    ----------
    type: string indicated whether this is an 'input' or 'output' port.
    width: bitwidth of the port.
    name: (TODO: remove? Previously only used for intermediate values).
    str: initializes a VerilogPort given a string containing a Verilog port
         declaration. (TODO: remove. Only used by FromVerilog.)
    """
    self.type  = type
    self.width = width
    self.name  = name
    self.parent = None
    self.connections = []
    self._value     = None
    if str:
      self.type, self.width, self.name  = self.parse( str )

  # TODO: add id?
  #def __repr__(self):
  #  return "Port(%s, %s, %s)" % (self.type, self.width, self.name)

  def __str__(self):
    if isinstance(self.width, str):
      return "%s %s %s" % (self.type, self.width, self.name)
    elif isinstance(self.width, int):
      if self.width == 1:
        return "%s %s" % (self.type, self.name)
      else :
        return "%s [%d:0] %s" % (self.type, self.width-1, self.name)

  def __ne__(self, target):
    """Connection operator (<>), calls connect()."""
    self.connect(target)

  def __xor__(self, target):
    """Bitwise xor (^)."""
    # TODO: returns an int, not a port. Is this okay?
    #temp = VerilogPort(name='xor_temp') #temp.value = self.value ^ target.value
    temp = self.value ^ target.value
    return temp

  def __rxor__(self, target):
    """Bitwise xor (^), allows xor-ing a VerilogPort with an int object."""
    temp = self.value ^ target
    return temp

  def __and__(self, target):
    """Bitwise and (&)."""
    # TODO: returns an int, not a port. Is this okay?
    #temp = VerilogPort(name='and_temp') #temp.value = self.value & target.value
    temp = self.value & target.value
    return temp

  def __or__(self, target):
    """Bitwise or (|)."""
    # TODO: returns an int, not a port. Is this okay?
    #temp = VerilogPort(name='or_temp') #temp.value = self.value | target.value
    temp = self.value | target.value
    return temp

  def __ilshift__(self, target):
    """Assignment operator (<<=). Sets value of this port."""
    # TODO: debug_assign
    #print type(self), self.parent+'.'+self.name, self.value, '<<=',
    # TODO: handles both int and VerilogPort. Better way?
    if not isinstance(target, int): self.value = target.value
    else:                           self.value = target
    return self

  def __getitem__(self, addr):
    """Bitfield access ([]). Returns a VeriogSlice object.

    TODO: only works for connectivity, not logic?
    """
    #print "@__getitem__", type(addr), addr, str(addr)
    # TODO: handle slices here or in Slice type?
    return VerilogSlice(self, 1, addr)

  def connect(self, target):
    """Creates a connection with a VerilogPort or VerilogSlice.

    TODO: implement connections with a VerilogWire?
    """
    # TODO: throw an exception if the other object is not a VerilogPort
    # TODO: support wires?
    # TODO: do we want to use an assert here
    if isinstance(target, int):
      self.connections += [VerilogConstant(target, self.width)]
      self._value     = ValueNode(self.width, target)
      #print "CreateConstValueNode:", self.parent, self.name, self._value
    elif isinstance(target, VerilogSlice):
      assert self.width == target.width
      self.connections.append(   target )
      target.connections.append( self   )
      if target._value:
        self._value = target
      else:
        self._value = target
        target._value = ValueNode(target.parent_ptr.width)
        #print "CreateValueNode:", self.parent, self.name, target._value
    else:
      assert self.width == target.width
      self.connections.append(   target )
      target.connections.append( self   )
      if target._value:
        self._value = target._value
      else:
        self._value = ValueNode(self.width)
        #print "CreateValueNode:", self.parent, self.name, self._value
        target._value = self._value

  def parse(self, line):
    """Sets port parameters using a Verilog port declaration.

    TODO: remove only used by FromVerilog.
    """
    tokens = line.strip().strip(',').split()
    type = tokens[0]
    if len(tokens) == 2:
      name  = tokens[1]
      width = 1
    elif len(tokens) == 3:
      name = tokens[2]
      width = tokens[1]
    return type, width, name

  @property
  def value(self):
    """Value on the port."""
    if self._value:
      return self._value.value
    else:
      return self._value
  @value.setter
  def value(self, value):
    #print "PORT:", self.parent+'.'+self.name
    # TODO: add as debug?
    #if isinstance(self, VerilogSlice):
    #  print "  writing", 'SLICE.'+self.name, ':   ', self.value
    #else:
    #  print "  writing", self.parent+'.'+self.name, ':   ', self.value
    # TODO: change how ValueNode instantiation occurs
    if not self._value:
      print "// WARNING: writing to unconnected node {0}.{1}!".format(
            self.parent, self.name)
      self._value = ValueNode(self.width, value)
    else:
      self._value.value = value
      #sim.add_event(self, self.connection)


class InPort(VerilogPort):
  """User visible implementation of an input port."""

  def __init__(self, width=None):
    """Constructor for an InPort object.

    Parameters
    ----------
    width: bitwidth of the port.
    """
    super(InPort, self).__init__('input', width)


class OutPort(VerilogPort):

  """User visible implementation of an output port."""

  def __init__(self, width=None):
    """Constructor for an InPort object.

    Parameters
    ----------
    width: bitwidth of the port.
    """
    super(OutPort, self).__init__('output', width)


class VerilogConstant(object):

  """Hidden class for storing a constant valued node."""

  def __init__(self, value, width):
    """Constructor for a VerilogWire object.

    Parameters
    ----------
    value: value of the constant.
    width: bitwidth of the constant.
    """
    self.value = value
    self.width = width
    self.type  = 'constant'
    self.name  = "%d'd%d" % (self.width, self.value)
    self.parent = None

  def __repr__(self):
    return "Constant(%s, %s)" % (self.value, self.width)

  def __str__(self):
    return self.name


class VerilogWire(object):

  """User visible (?) class to represent wire/connection objects.

  Not sure if VerilogWire objects should be user visible, or should always be
  inferred based on connectivity/logic.  Currently only inferred based on
  connectivity...
  """

  def __init__(self, name, width):
    """Constructor for a VerilogWire object.

    Parameters
    ----------
    name: name of the wire.
    width: bitwidth of the wire.
    """
    self.name  = name
    self.width = width
    self.type  = "wire"

  def __repr__(self):
    return "Wire(%s, %s)" % (self.name, self.width)

  def __str__(self):
    # TODO: this seems weird.
    if isinstance(self.width, str):
      return "wire %s %s;" % (self.width, self.name)
    elif isinstance(self.width, int):
      if self.width == 1:
        return "wire %s;" % (self.name)
      else :
        return "wire [%d:0] %s;" % (self.width-1, self.name)


class VerilogParam(object):

  """REMOVE: class to represent Verilog parameters. Only used by FromVerilog?"""

  def __init__(self, name, value):
    self.name  = name
    self.value = value

  def __init__(self, line):
    self.name, self.value = self.parse(line)

  def __repr__(self):
    return "Param(%s = %s)" % (self.name, self.value)

  def parse(self, line):
    tokens = line.strip().split()
    name  = tokens[1]
    value = tokens[3].strip(',')
    return name, value


class VerilogModule(object):

  """User visible base class for hardware models.

  Provides utility classes for elaborating connectivity between components,
  giving instantiated subcomponents proper names, and building datastructures
  that can be leveraged by various MTL tools.

  Any user implemented model that wishes to make use of the various MTL tools
  should subclass this.
  """

  def elaborate(self, iname='toplevel'):
    """Elaborate a MTL model (construct hierarchy, name modules, etc.).

    The elaborate() function must be called on an instantiated toplevel module
    before it is passed to any MTL tools!
    """
    # TODO: call elaborate() in the tools?
    target = self
    # TODO: better way to set the name?
    target.class_name = target.__class__.__name__
    target.parent = None
    target.name = iname
    target.wires = []
    target.ports = []
    target.submodules = []
    # TODO: do all ports first?
    # Get the names of all ports and submodules
    for name, obj in target.__dict__.items():
      # TODO: make ports, submodules, wires _ports, _submodules, _wires
      if (name is not 'ports' and name is not 'submodules'):
        self.check_type(target, name, obj)

  def check_type(self, target, name, obj):
    """Utility method to specialize elaboration actions based on object type."""
    # If object is a port, add it to our ports list
    if isinstance(obj, VerilogPort):
      obj.name = name
      obj.parent = target
      target.ports += [obj]
    # If object is a submodule, add it to our submodules list and recursively
    # call elaborate() on it
    elif isinstance(obj, VerilogModule):
      # TODO: change obj.type to obj.inst_type?
      obj.type = obj.__class__.__name__
      obj.elaborate( name )
      obj.parent = target
      target.submodules += [obj]
    # If the object is a list, iterate through each item in the list and
    # recursively call the check_type() utility function
    elif isinstance(obj, list):
      for i, item in enumerate(obj):
        item_name = "%s_%d" % (name, i)
        self.check_type(target, item_name, item)

