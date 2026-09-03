cuda_tile.module @m {
  entry @compact(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1xi32>
    %3 = broadcast %2 : tile<1xi32> -> tile<128xi32>
    %4 = iota : tile<128xi32>
    %5 = addi %3, %4 : tile<128xi32>
    %6 = constant <i32: 100> : tile<128xi32>
    %7 = cmpi less_than %5, %6, signed : tile<128xi32> -> tile<128xi1>
    %8 = constant <f64: 0.0> : tile<128xf64>
    %9 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %10 = broadcast %9 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %11 = offset %10, %5 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %12, %13 = load_ptr_tko weak %11, %7, %8 token=%0 : tile<128xptr<f64>>, tile<128xi1>, tile<128xf64> -> tile<128xf64>, token
    %14 = constant <f64: 0.0> : tile<128xf64>
    %15 = cmpf greater_than ordered %12, %14 : tile<128xf64> -> tile<128xi1>
    %16 = constant <i1: 0> : tile<128xi1>
    %17 = select %7, %15, %16 : tile<128xi1>, tile<128xi1>
    %18 = constant <i32: 1> : tile<128xi32>
    %19 = constant <i32: 0> : tile<128xi32>
    %20 = select %17, %18, %19 : tile<128xi1>, tile<128xi32>
    %21 = scan %20 dim=0 reverse=false identities=[0 : i32] : tile<128xi32> -> tile<128xi32> (%22: tile<i32>, %23: tile<i32>) {
      %24 = addi %22, %23 : tile<i32>
      yield %24 : tile<i32>
    }
    %25 = subi %21, %20 : tile<128xi32>
    %26 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %28 = offset %27, %25 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %29 = store_ptr_tko weak %28, %12, %17 token=%13 : tile<128xptr<f64>>, tile<128xf64>, tile<128xi1> -> token
    return
  }
}
