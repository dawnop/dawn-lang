cuda_tile.module @m {
  entry @ols_elim(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<8x16xi32>
    %2 = reshape %arg1 : tile<ptr<i32>> -> tile<1x1xptr<i32>>
    %3 = broadcast %2 : tile<1x1xptr<i32>> -> tile<8x16xptr<i32>>
    %4 = offset %3, %1 : tile<8x16xptr<i32>>, tile<8x16xi32> -> tile<8x16xptr<i32>>
    %5, %6 = load_ptr_tko weak %4 token=%0 : tile<8x16xptr<i32>> -> tile<8x16xi32>, token
    %7 = constant <i32: 0> : tile<i32>
    %8 = reshape %7 : tile<i32> -> tile<1x1xi32>
    %9 = broadcast %8 : tile<1x1xi32> -> tile<8x16xi32>
    %10 = iota : tile<8xi32>
    %11 = reshape %10 : tile<8xi32> -> tile<8x1xi32>
    %12 = broadcast %11 : tile<8x1xi32> -> tile<8x16xi32>
    %13 = addi %9, %12 : tile<8x16xi32>
    %14 = iota : tile<16xi32>
    %15 = reshape %14 : tile<16xi32> -> tile<1x16xi32>
    %16 = broadcast %15 : tile<1x16xi32> -> tile<8x16xi32>
    %17 = constant <i32: 0> : tile<8x16xi32>
    %18 = muli %16, %17 : tile<8x16xi32>
    %19 = addi %13, %18 : tile<8x16xi32>
    %20 = constant <i32: 0> : tile<i32>
    %21 = reshape %20 : tile<i32> -> tile<1x1xi32>
    %22 = broadcast %21 : tile<1x1xi32> -> tile<8x16xi32>
    %23 = iota : tile<8xi32>
    %24 = reshape %23 : tile<8xi32> -> tile<8x1xi32>
    %25 = broadcast %24 : tile<8x1xi32> -> tile<8x16xi32>
    %26 = constant <i32: 0> : tile<8x16xi32>
    %27 = muli %25, %26 : tile<8x16xi32>
    %28 = addi %22, %27 : tile<8x16xi32>
    %29 = iota : tile<16xi32>
    %30 = reshape %29 : tile<16xi32> -> tile<1x16xi32>
    %31 = broadcast %30 : tile<1x16xi32> -> tile<8x16xi32>
    %32 = addi %28, %31 : tile<8x16xi32>
    %33 = constant <i32: 16> : tile<8x16xi32>
    %34 = muli %5, %33 : tile<8x16xi32>
    %35 = addi %34, %5 : tile<8x16xi32>
    %36 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %37 = broadcast %36 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %38 = offset %37, %35 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %39, %40 = load_ptr_tko weak %38 token=%6 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
    %41 = addi %34, %32 : tile<8x16xi32>
    %42 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %43 = broadcast %42 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %44 = offset %43, %41 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %45, %46 = load_ptr_tko weak %44 token=%40 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
    %47 = divf %45, %39 rounding<nearest_even> : tile<8x16xf64>
    %48 = constant <i32: 16> : tile<8x16xi32>
    %49 = muli %19, %48 : tile<8x16xi32>
    %50 = addi %49, %5 : tile<8x16xi32>
    %51 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %52 = broadcast %51 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %53 = offset %52, %50 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %54, %55 = load_ptr_tko weak %53 token=%46 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
    %56 = constant <i32: 0> : tile<i32>
    %57 = reshape %56 : tile<i32> -> tile<1x1xi32>
    %58 = broadcast %57 : tile<1x1xi32> -> tile<8x16xi32>
    %59 = iota : tile<8xi32>
    %60 = reshape %59 : tile<8xi32> -> tile<8x1xi32>
    %61 = broadcast %60 : tile<8x1xi32> -> tile<8x16xi32>
    %62 = constant <i32: 16> : tile<8x16xi32>
    %63 = muli %61, %62 : tile<8x16xi32>
    %64 = addi %58, %63 : tile<8x16xi32>
    %65 = iota : tile<16xi32>
    %66 = reshape %65 : tile<16xi32> -> tile<1x16xi32>
    %67 = broadcast %66 : tile<1x16xi32> -> tile<8x16xi32>
    %68 = addi %64, %67 : tile<8x16xi32>
    %69 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %70 = broadcast %69 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %71 = offset %70, %68 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %72, %73 = load_ptr_tko weak %71 token=%55 : tile<8x16xptr<f64>> -> tile<8x16xf64>, token
    %74 = mulf %54, %47 rounding<nearest_even> : tile<8x16xf64>
    %75 = subf %72, %74 rounding<nearest_even> : tile<8x16xf64>
    %76 = constant <i32: 0> : tile<i32>
    %77 = cmpi equal %19, %5, signed : tile<8x16xi32> -> tile<8x16xi1>
    %78 = select %77, %47, %75 : tile<8x16xi1>, tile<8x16xf64>
    %79 = reshape %76 : tile<i32> -> tile<1x1xi32>
    %80 = broadcast %79 : tile<1x1xi32> -> tile<8x16xi32>
    %81 = iota : tile<8xi32>
    %82 = reshape %81 : tile<8xi32> -> tile<8x1xi32>
    %83 = broadcast %82 : tile<8x1xi32> -> tile<8x16xi32>
    %84 = constant <i32: 16> : tile<8x16xi32>
    %85 = muli %83, %84 : tile<8x16xi32>
    %86 = addi %80, %85 : tile<8x16xi32>
    %87 = iota : tile<16xi32>
    %88 = reshape %87 : tile<16xi32> -> tile<1x16xi32>
    %89 = broadcast %88 : tile<1x16xi32> -> tile<8x16xi32>
    %90 = addi %86, %89 : tile<8x16xi32>
    %91 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %92 = broadcast %91 : tile<1x1xptr<f64>> -> tile<8x16xptr<f64>>
    %93 = offset %92, %90 : tile<8x16xptr<f64>>, tile<8x16xi32> -> tile<8x16xptr<f64>>
    %94 = store_ptr_tko weak %93, %78 token=%73 : tile<8x16xptr<f64>>, tile<8x16xf64> -> token
    return
  }
}
