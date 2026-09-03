cuda_tile.module @m {
  entry @merge_rank(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = constant <f64: 1.0> : tile<32x32xf64>
    %3 = constant <f64: 0.0> : tile<32x32xf64>
    %4 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %5 = broadcast %4 : tile<1x1xi32> -> tile<32x32xi32>
    %6 = iota : tile<32xi32>
    %7 = reshape %6 : tile<32xi32> -> tile<32x1xi32>
    %8 = broadcast %7 : tile<32x1xi32> -> tile<32x32xi32>
    %9 = addi %5, %8 : tile<32x32xi32>
    %10 = iota : tile<32xi32>
    %11 = reshape %10 : tile<32xi32> -> tile<1x32xi32>
    %12 = broadcast %11 : tile<1x32xi32> -> tile<32x32xi32>
    %13 = constant <i32: 0> : tile<32x32xi32>
    %14 = muli %12, %13 : tile<32x32xi32>
    %15 = addi %9, %14 : tile<32x32xi32>
    %16 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %17 = broadcast %16 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %18 = offset %17, %15 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %19, %20 = load_ptr_tko weak %18 token=%0 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %21 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %22 = broadcast %21 : tile<1x1xi32> -> tile<32x32xi32>
    %23 = iota : tile<32xi32>
    %24 = reshape %23 : tile<32xi32> -> tile<32x1xi32>
    %25 = broadcast %24 : tile<32x1xi32> -> tile<32x32xi32>
    %26 = constant <i32: 0> : tile<32x32xi32>
    %27 = muli %25, %26 : tile<32x32xi32>
    %28 = addi %22, %27 : tile<32x32xi32>
    %29 = iota : tile<32xi32>
    %30 = reshape %29 : tile<32xi32> -> tile<1x32xi32>
    %31 = broadcast %30 : tile<1x32xi32> -> tile<32x32xi32>
    %32 = addi %28, %31 : tile<32x32xi32>
    %33 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %34 = broadcast %33 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
    %35 = offset %34, %32 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
    %36, %37 = load_ptr_tko weak %35 token=%20 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
    %38 = cmpf less_than ordered %36, %19 : tile<32x32xf64> -> tile<32x32xi1>
    %39 = select %38, %2, %3 : tile<32x32xi1>, tile<32x32xf64>
    %40 = cmpf less_than_or_equal ordered %19, %36 : tile<32x32xf64> -> tile<32x32xi1>
    %41 = select %40, %2, %3 : tile<32x32xi1>, tile<32x32xf64>
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
    %59, %60 = load_ptr_tko weak %58 token=%37 : tile<32xptr<f64>> -> tile<32xf64>, token
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
