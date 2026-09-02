cuda_tile.module @m {
  entry @softmax(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
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
    %13 = constant <f64: 0.0> : tile<1024xf64>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %15 = broadcast %14 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %16 = offset %15, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %17, %18 = load_ptr_tko weak %16, %11, %12 token=%0 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %19 = reduce %17 dim=0 identities=[-Infinity : f64] : tile<1024xf64> -> tile<f64> (%20: tile<f64>, %21: tile<f64>) {
      %22 = maxf %20, %21 : tile<f64>
      yield %22 : tile<f64>
    }
    %23 = reshape %19 : tile<f64> -> tile<1xf64>
    %24 = broadcast %23 : tile<1xf64> -> tile<1024xf64>
    %25 = subf %17, %24 rounding<nearest_even> : tile<1024xf64>
    %26 = exp %25 : tile<1024xf64>
    %27 = select %11, %26, %13 : tile<1024xi1>, tile<1024xf64>
    %28 = reduce %27 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%29: tile<f64>, %30: tile<f64>) {
      %31 = addf %29, %30 rounding<nearest_even> : tile<f64>
      yield %31 : tile<f64>
    }
    %32 = reshape %28 : tile<f64> -> tile<1xf64>
    %33 = broadcast %32 : tile<1xf64> -> tile<1024xf64>
    %34 = divf %26, %33 rounding<nearest_even> : tile<1024xf64>
    %35 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %36 = broadcast %35 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %37 = offset %36, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %38 = store_ptr_tko weak %37, %34, %11 token=%18 : tile<1024xptr<f64>>, tile<1024xf64>, tile<1024xi1> -> token
    return
  }
}
