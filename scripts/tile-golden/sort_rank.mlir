cuda_tile.module @m {
  entry @sort_rank(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %3 = broadcast %2 : tile<1x1xi32> -> tile<32x32xi32>
    %4 = iota : tile<32xi32>
    %5 = reshape %4 : tile<32xi32> -> tile<32x1xi32>
    %6 = broadcast %5 : tile<32x1xi32> -> tile<32x32xi32>
    %7 = addi %3, %6 : tile<32x32xi32>
    %8 = iota : tile<32xi32>
    %9 = reshape %8 : tile<32xi32> -> tile<1x32xi32>
    %10 = broadcast %9 : tile<1x32xi32> -> tile<32x32xi32>
    %11 = constant <i32: 0> : tile<32x32xi32>
    %12 = muli %10, %11 : tile<32x32xi32>
    %13 = addi %7, %12 : tile<32x32xi32>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %15 = broadcast %14 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %16 = offset %15, %13 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %17, %18 = load_ptr_tko weak %16 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %19 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %20 = broadcast %19 : tile<1x1xi32> -> tile<32x32xi32>
    %21 = iota : tile<32xi32>
    %22 = reshape %21 : tile<32xi32> -> tile<32x1xi32>
    %23 = broadcast %22 : tile<32x1xi32> -> tile<32x32xi32>
    %24 = constant <i32: 0> : tile<32x32xi32>
    %25 = muli %23, %24 : tile<32x32xi32>
    %26 = addi %20, %25 : tile<32x32xi32>
    %27 = iota : tile<32xi32>
    %28 = reshape %27 : tile<32xi32> -> tile<1x32xi32>
    %29 = broadcast %28 : tile<1x32xi32> -> tile<32x32xi32>
    %30 = addi %26, %29 : tile<32x32xi32>
    %31 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %32 = broadcast %31 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %33 = offset %32, %30 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %34, %35 = load_ptr_tko weak %33 token=%18 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %36 = cmpf equal ordered %34, %17 : tile<32x32xf64> -> tile<32x32xi1>
    %37 = cmpi less_than %30, %13, signed : tile<32x32xi32> -> tile<32x32xi1>
    %38 = constant <i1: 0> : tile<32x32xi1>
    %39 = select %36, %37, %38 : tile<32x32xi1>, tile<32x32xi1>
    %40 = cmpf less_than ordered %34, %17 : tile<32x32xf64> -> tile<32x32xi1>
    %41 = constant <i1: 1> : tile<32x32xi1>
    %42 = select %40, %41, %39 : tile<32x32xi1>, tile<32x32xi1>
    %43 = constant <f64: 1.0> : tile<32x32xf64>
    %44 = constant <f64: 0.0> : tile<32x32xf64>
    %45 = select %42, %43, %44 : tile<32x32xi1>, tile<32x32xf64>
    %46 = reduce %45 dim=1 identities=[0.0 : f64] : tile<32x32xf64> -> tile<32xf64> (%47: tile<f64>, %48: tile<f64>) {
      %49 = addf %47, %48 rounding<nearest_even> : tile<f64>
      yield %49 : tile<f64>
    }
    %50 = ftoi %46 signed rounding<nearest_int_to_zero> : tile<32xf64> -> tile<32xi32>
    %51 = reshape %1 : tile<i32> -> tile<1xi32>
    %52 = broadcast %51 : tile<1xi32> -> tile<32xi32>
    %53 = iota : tile<32xi32>
    %54 = addi %52, %53 : tile<32xi32>
    %55 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %56 = broadcast %55 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %57 = offset %56, %54 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %58, %59 = load_ptr_tko weak %57 token=%35 : tile<32xptr<f64>> -> tile<32xf64>, token
    %60 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %61 = broadcast %60 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %62 = offset %61, %50 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %63 = store_ptr_tko weak %62, %58 token=%59 : tile<32xptr<f64>>, tile<32xf64> -> token
    return
  }
}
