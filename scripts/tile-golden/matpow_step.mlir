cuda_tile.module @m {
  entry @matpow_step(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %3 = broadcast %2 : tile<1x1xi32> -> tile<32x32xi32>
    %4 = iota : tile<32xi32>
    %5 = reshape %4 : tile<32xi32> -> tile<32x1xi32>
    %6 = broadcast %5 : tile<32x1xi32> -> tile<32x32xi32>
    %7 = constant <i32: 32> : tile<32x32xi32>
    %8 = muli %6, %7 : tile<32x32xi32>
    %9 = addi %3, %8 : tile<32x32xi32>
    %10 = iota : tile<32xi32>
    %11 = reshape %10 : tile<32xi32> -> tile<1x32xi32>
    %12 = broadcast %11 : tile<1x32xi32> -> tile<32x32xi32>
    %13 = addi %9, %12 : tile<32x32xi32>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %15 = broadcast %14 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %16 = offset %15, %13 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %17, %18 = load_ptr_tko weak %16 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %19 = constant <i32: 0> : tile<i32>
    %20 = reshape %19 : tile<i32> -> tile<1x1xi32>
    %21 = broadcast %20 : tile<1x1xi32> -> tile<32x32xi32>
    %22 = iota : tile<32xi32>
    %23 = reshape %22 : tile<32xi32> -> tile<32x1xi32>
    %24 = broadcast %23 : tile<32x1xi32> -> tile<32x32xi32>
    %25 = constant <i32: 32> : tile<32x32xi32>
    %26 = muli %24, %25 : tile<32x32xi32>
    %27 = addi %21, %26 : tile<32x32xi32>
    %28 = iota : tile<32xi32>
    %29 = reshape %28 : tile<32xi32> -> tile<1x32xi32>
    %30 = broadcast %29 : tile<1x32xi32> -> tile<32x32xi32>
    %31 = addi %27, %30 : tile<32x32xi32>
    %32 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %33 = broadcast %32 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %34 = offset %33, %31 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %35, %36 = load_ptr_tko weak %34 token=%18 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %37 = constant <i32: 0> : tile<i32>
    %38 = constant <f64: 0.0> : tile<32x32xf64>
    %39 = mmaf %17, %35, %38 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
    %40 = reshape %37 : tile<i32> -> tile<1x1xi32>
    %41 = broadcast %40 : tile<1x1xi32> -> tile<32x32xi32>
    %42 = iota : tile<32xi32>
    %43 = reshape %42 : tile<32xi32> -> tile<32x1xi32>
    %44 = broadcast %43 : tile<32x1xi32> -> tile<32x32xi32>
    %45 = constant <i32: 32> : tile<32x32xi32>
    %46 = muli %44, %45 : tile<32x32xi32>
    %47 = addi %41, %46 : tile<32x32xi32>
    %48 = iota : tile<32xi32>
    %49 = reshape %48 : tile<32xi32> -> tile<1x32xi32>
    %50 = broadcast %49 : tile<1x32xi32> -> tile<32x32xi32>
    %51 = addi %47, %50 : tile<32x32xi32>
    %52 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %53 = broadcast %52 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %54 = offset %53, %51 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %55 = store_ptr_tko weak %54, %39 token=%36 : tile<32x32xptr<f64>>, tile<32x32xf64> -> token
    return
  }
}
