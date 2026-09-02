cuda_tile.module @m {
  entry @argmax(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = constant <i32: 1000> : tile<1024xi32>
    %11 = cmpi less_than %9, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <f64: -Infinity> : tile<1024xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %15 = offset %14, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %18, %19 = reduce %16, %9 dim=0 identities=[-Infinity : f64, -1 : i32] : tile<1024xf64>, tile<1024xi32> -> tile<f64>, tile<i32> (%20: tile<f64>, %21: tile<f64>, %22: tile<i32>, %23: tile<i32>) {
      %24 = cmpf greater_than ordered %20, %21 : tile<f64> -> tile<i1>
      %25 = select %24, %20, %21 : tile<i1>, tile<f64>
      %26 = select %24, %22, %23 : tile<i1>, tile<i32>
      yield %25, %26 : tile<f64>, tile<i32>
    }
    %27 = reshape %19 : tile<i32> -> tile<1xi32>
    %28 = broadcast %27 : tile<1xi32> -> tile<1024xi32>
    %29 = cmpi equal %9, %28, signed : tile<1024xi32> -> tile<1024xi1>
    %30 = constant <f64: 1.0> : tile<1024xf64>
    %31 = constant <f64: 0.0> : tile<1024xf64>
    %32 = select %29, %30, %31 : tile<1024xi1>, tile<1024xf64>
    %33 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %34 = broadcast %33 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %35 = offset %34, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %36 = store_ptr_tko weak %35, %32, %11 token=%17 : tile<1024xptr<f64>>, tile<1024xf64>, tile<1024xi1> -> token
    return
  }
}
