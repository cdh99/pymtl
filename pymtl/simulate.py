#=========================================================================
# Simulation Tool
#=========================================================================
"""Tool for simulating MTL models.

This module contains classes which construct a simulator given a MTL model
for execution in the python interpreter.
"""

from collections import deque, defaultdict
import ast, _ast
import inspect
import pprint

from model import *
from vcd import VCDUtil

# TODO: make commandline parameter
debug_hierarchy = False

#=========================================================================
# SimulationTool
#=========================================================================

class SimulationTool():

  """User visible class implementing a tool for simulating MTL models.

  This class takes a MTL model instance and creates a simulator for execution
  in the python interpreter.
  """

  #-----------------------------------------------------------------------
  # Constructor
  #-----------------------------------------------------------------------

  def __init__(self, model):
    """Construct a simulator from a MTL model.

    Parameters
    ----------
    model: an instantiated MTL model (Model).
    """
    # TODO: call elaborate on model?
    if not model.is_elaborated():
      msg  = "cannot initialize {0} tool.\n".format(self.__class__.__name__)
      msg += "Provided model has not been elaborated yet!!!"
      raise Exception(msg)
    self.model = model
    self.num_cycles      = 0
    self.vnode_callbacks = defaultdict(list)
    self.rnode_callbacks = []
    self.event_queue     = deque()
    self.posedge_clk_fns = []
    #self.node_groups     = []
    # Set by VCDUtil
    self.vcd = False
    self.o   = None

    # Actually construct the simulator
    self.construct_sim()

  #-----------------------------------------------------------------------
  # Cycle
  #-----------------------------------------------------------------------

  def cycle(self):
    """Execute a single cycle in the simulator.

    Executes any functions in the event queue and increments the num_cycles
    count.

    TODO: execute all @posedge, @negedge decorated functions.
    """
    # Call all events generated by input changes
    self.eval_combinational()

    # TODO: Hacky auto clock generation
    #       this self.model.clk.value changes behavior event queue
    #       behavior depending on whether vcd output is enabled or not... bad
    if self.vcd:
      print >> self.o, "#%s" % (10 * self.num_cycles)
    self.model.clk.value = 0

    if self.vcd:
      print >> self.o, "#%s" % ((10 * self.num_cycles) + 5)
    self.model.clk.value = 1

    # Call all rising edge triggered functions
    for func in self.posedge_clk_fns:
      func()

    # Then call clock() on all registers
    while self.rnode_callbacks:
      reg = self.rnode_callbacks.pop()
      reg.clock()

    # Call all events generated by synchronous logic
    self.eval_combinational()

    self.num_cycles += 1

  #-----------------------------------------------------------------------
  # Print Line Trace
  #-----------------------------------------------------------------------
  # Framework should take care of printing cycle. -cbatten

  def print_line_trace(self):
    print "{:>3}:".format( self.num_cycles ), self.model.line_trace()

  #-----------------------------------------------------------------------
  # Eval
  #-----------------------------------------------------------------------

  def eval_combinational(self):
    """Evaluates all events in the combinational logic event queue."""
    while self.event_queue:
      func = self.event_queue.pop()
      func()

  #-----------------------------------------------------------------------
  # Reset
  #-----------------------------------------------------------------------

  def reset(self):
    """Sets the reset signal high and cycles the simulator."""
    self.model.reset.value = 1
    self.cycle()
    self.cycle()
    self.model.reset.value = 0

  #-----------------------------------------------------------------------
  # Dump VCD
  #-----------------------------------------------------------------------

  def dump_vcd(self, outfile=None):
    """Configure the simulator to dump VCD output during simulation."""
    VCDUtil(self, outfile)

  #-----------------------------------------------------------------------
  # Enable Line Trace
  #-----------------------------------------------------------------------

  def en_line_trace(self, enabled=True):
    """Configure the simulator to dump line trace during simulation."""
    self.model._line_trace_en = enabled

  #-----------------------------------------------------------------------
  # Add Callback Event
  #-----------------------------------------------------------------------

  def add_event(self, value_node):
    """Add an event to the simulator event queue for later execution.

    This function will check if the written Node instance has any
    registered events (functions decorated with @combinational), and if so, adds
    them to the event queue.
    """
    # TODO: debug_event
    #print "    ADDEVENT: VALUE", value_node, value_node.value, value_node in self.vnode_callbacks
    if value_node in self.vnode_callbacks:
      funcs = self.vnode_callbacks[value_node]
      for func in funcs:
        if func not in self.event_queue:
          self.event_queue.appendleft(func)

  #-----------------------------------------------------------------------
  # Construct Simulator
  #-----------------------------------------------------------------------

  def construct_sim(self):
    """Construct a simulator for the provided model by adding necessary hooks."""
    # build up the node_groups data structure
    self.find_node_groupings(self.model)

    # walk the AST of each module to create sensitivity lists and add registers
    self.register_decorated_functions(self.model)

  #-----------------------------------------------------------------------
  # Find Node Groupings
  #-----------------------------------------------------------------------
  # TODO: this is a hacky way to connect the ConnectionGraph and the
  # ValueGraph. This is also poorly named.  Fixed later.

  def find_node_groupings(self, model):
    """Walk all connections to find where Node objects should be placed."""
    if debug_hierarchy:
      print 70*'-'
      print "Model:", model
      print "Ports:"
      pprint.pprint( model._ports, indent=3 )
      print "Submodules:"
      pprint.pprint( model._submodules, indent=3 )

    # Walk ports to add value nodes.  Do leaves or toplevel first?
    for p in model._ports:
      #self.add_to_node_groups(p)
      p.node.sim = self

    for w in model._wires:
      #self.add_to_node_groups(w)
      w.node.sim = self

    for m in model._submodules:
      self.find_node_groupings( m )

  #-----------------------------------------------------------------------
  # Add to Node Groups
  #-----------------------------------------------------------------------
  # DEPRECATED, UNUSED!!!

  def add_to_node_groups(self, port):
    """Add the port to a node group, merge groups if necessary.

    Parameters
    ----------
    port: a Port instance.
    """
    group = set([port])
    group.update( port.connections )
    # Utility function for our list comprehension below.  If the group and set
    # are disjoint, return true.  Otherwise return false and join the set to
    # the group.
    def disjoint(group,s):
      if not group.isdisjoint(s):
        group.update(s)
        return False
      else:
        return True
    self.node_groups[:] = [x for x in self.node_groups if disjoint(group, x)]
    self.node_groups += [ group ]

  #-----------------------------------------------------------------------
  # Register Decorated Functions
  #-----------------------------------------------------------------------

  def register_decorated_functions(self, model):
    """Utility method which detects the sensitivity list of annotated functions.

    This method uses the DecoratedFunctionVisitor class to walk the AST of the
    provided model and register any functions annotated with special
    decorators.
    """

    # Create an AST Tree
    model_class = model.__class__
    src = inspect.getsource( model_class )
    tree = ast.parse( src )
    #print
    #import debug_utils
    #debug_utils.print_ast(tree)
    comb_funcs    = set()
    posedge_funcs = set()

    # Walk the tree to inspect a given modules combinational blocks and
    # build a sensitivity list from it,
    # only gives us function names... still need function pointers
    DecoratedFunctionVisitor( comb_funcs, posedge_funcs ).visit( tree )

    # Iterate through all @combinational decorated function names we detected,
    # retrieve their associated function pointer, then add entries for each
    # item in the function's sensitivity list to vnode_callbacks
    for func_name, sensitivity_list in model._newsenses.items():
      #print '@@@', func_name, [(x.parent.name, x.name) for x in sensitivity_list]
      func_ptr = model.__getattribute__(func_name)
      for signal in sensitivity_list:
        value_ptr = signal.node
        self.vnode_callbacks[value_ptr] += [func_ptr]
        # Prime the simulation by putting all events on the event_queue
        # This will make sure all nodes come out of reset in a consistent
        # state. TODO: put this in reset() instead?
        if func_ptr not in self.event_queue:
          self.event_queue.appendleft(func_ptr)

    # TODO: old implementation, remove me!
    #for func_name in comb_funcs:
    #  func_ptr = model.__getattribute__(func_name)
    #  for input_port in model._senses:
    #    value_ptr = input_port.node
    #    #if isinstance(value_ptr, Slice):
    #    #  value_ptr = value_ptr._value
    #    if value_ptr not in self.vnode_callbacks:
    #      self.vnode_callbacks[value_ptr] = []
    #    self.vnode_callbacks[value_ptr] += [func_ptr]

    # Add all posedge_clk functions
    for func_name in posedge_funcs:
      func_ptr = model.__getattribute__(func_name)
      self.posedge_clk_fns += [func_ptr]

    # Add all posedge_clk functions
    for m in model._submodules:
      self.register_decorated_functions( m )

#=========================================================================
# Decorated Function Visitor
#=========================================================================

class DecoratedFunctionVisitor(ast.NodeVisitor):
  """Hidden class for building a sensitivity list from the AST of a MTL model.

  This class takes the AST tree of a Model class and looks for any
  functions annotated with the @combinational decorator. Variables that perform
  loads in these functions are added to the sensitivity list (registry).
  """
  # http://docs.python.org/library/ast.html#abstract-grammar
  def __init__(self, comb_funcs, posedge_funcs):
    """Construct a new Decorated Function Visitor."""
    self.current_fn    = None
    self.comb_funcs    = comb_funcs
    self.posedge_funcs = posedge_funcs
    self.add_regs      = False

  def visit_FunctionDef(self, node):
    """Visit all functions, but only parse those with special decorators."""
    #pprint.pprint( dir(node) )
    #print "Function Name:", node.name
    if not node.decorator_list:
      return
    decorator_names = [x.id for x in node.decorator_list]
    if 'combinational' in decorator_names:
      self.comb_funcs.add( node.name )
    elif 'posedge_clk' in decorator_names:
      self.posedge_funcs.add( node.name )

