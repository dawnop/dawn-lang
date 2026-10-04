cuda_tile.module @m {
  entry @merge_rank(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
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
    %31 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %32 = broadcast %31 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %33 = offset %32, %30 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %34, %35 = load_ptr_tko weak %33 token=%18 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %36 = cmpf less_than ordered %34, %17 : tile<32x32xf64> -> tile<32x32xi1>
    %37 = constant <f64: 1.0> : tile<32x32xf64>
    %38 = constant <f64: 0.0> : tile<32x32xf64>
    %39 = select %36, %37, %38 : tile<32x32xi1>, tile<32x32xf64>
    %40 = cmpf less_than_or_equal ordered %17, %34 : tile<32x32xf64> -> tile<32x32xi1>
    %41 = select %40, %37, %38 : tile<32x32xi1>, tile<32x32xf64>
    %42 = reduce %39 dim=1 identities=[0.0 : f64] : tile<32x32xf64> -> tile<32xf64> (%43: tile<f64>, %44: tile<f64>) {
      %45 = addf %43, %44 rounding<nearest_even> : tile<f64>
      yield %45 : tile<f64>
    }
    %46 = reduce %41 dim=0 identities=[0.0 : f64] : tile<32x32xf64> -> tile<32xf64> (%47: tile<f64>, %48: tile<f64>) {
      %49 = addf %47, %48 rounding<nearest_even> : tile<f64>
      yield %49 : tile<f64>
    }
    %50 = reshape %1 : tile<i32> -> tile<1xi32>
    %51 = broadcast %50 : tile<1xi32> -> tile<32xi32>
    %52 = iota : tile<32xi32>
    %53 = addi %51, %52 : tile<32xi32>
    %54 = ftoi %42 signed rounding<nearest_int_to_zero> : tile<32xf64> -> tile<32xi32>
    %55 = addi %53, %54 : tile<32xi32>
    %56 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %57 = broadcast %56 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %58 = offset %57, %53 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %59, %60 = load_ptr_tko weak %58 token=%35 : tile<32xptr<f64>> -> tile<32xf64>, token
    %61 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %62 = broadcast %61 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %63 = offset %62, %55 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %64 = store_ptr_tko weak %63, %59 token=%60 : tile<32xptr<f64>>, tile<32xf64> -> token
    %65 = ftoi %46 signed rounding<nearest_int_to_zero> : tile<32xf64> -> tile<32xi32>
    %66 = addi %53, %65 : tile<32xi32>
    %67 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %68 = broadcast %67 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %69 = offset %68, %53 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %70, %71 = load_ptr_tko weak %69 token=%64 : tile<32xptr<f64>> -> tile<32xf64>, token
    %72 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %73 = broadcast %72 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %74 = offset %73, %66 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %75 = store_ptr_tko weak %74, %70 token=%71 : tile<32xptr<f64>>, tile<32xf64> -> token
    return
  }
}
