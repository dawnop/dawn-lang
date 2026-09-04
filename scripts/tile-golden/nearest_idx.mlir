cuda_tile.module @m {
  entry @nearest_idx(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 3> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 0> : tile<i32>
    %7 = reshape %6 : tile<i32> -> tile<1xi32>
    %8 = broadcast %7 : tile<1xi32> -> tile<64xi32>
    %9 = iota : tile<64xi32>
    %10 = constant <i32: 3> : tile<64xi32>
    %11 = muli %9, %10 : tile<64xi32>
    %12 = addi %8, %11 : tile<64xi32>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %15 = offset %14, %12 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %16, %17 = load_ptr_tko weak %15 token=%0 : tile<64xptr<f64>> -> tile<64xf64>, token
    %18 = constant <i32: 1> : tile<i32>
    %19 = reshape %18 : tile<i32> -> tile<1xi32>
    %20 = broadcast %19 : tile<1xi32> -> tile<64xi32>
    %21 = iota : tile<64xi32>
    %22 = constant <i32: 3> : tile<64xi32>
    %23 = muli %21, %22 : tile<64xi32>
    %24 = addi %20, %23 : tile<64xi32>
    %25 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %26 = broadcast %25 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %27 = offset %26, %24 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %28, %29 = load_ptr_tko weak %27 token=%17 : tile<64xptr<f64>> -> tile<64xf64>, token
    %30 = constant <i32: 2> : tile<i32>
    %31 = reshape %30 : tile<i32> -> tile<1xi32>
    %32 = broadcast %31 : tile<1xi32> -> tile<64xi32>
    %33 = iota : tile<64xi32>
    %34 = constant <i32: 3> : tile<64xi32>
    %35 = muli %33, %34 : tile<64xi32>
    %36 = addi %32, %35 : tile<64xi32>
    %37 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %38 = broadcast %37 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %39 = offset %38, %36 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %40, %41 = load_ptr_tko weak %39 token=%29 : tile<64xptr<f64>> -> tile<64xf64>, token
    %42 = reshape %5 : tile<i32> -> tile<1xi32>
    %43 = broadcast %42 : tile<1xi32> -> tile<64xi32>
    %44 = iota : tile<64xi32>
    %45 = constant <i32: 0> : tile<64xi32>
    %46 = muli %44, %45 : tile<64xi32>
    %47 = addi %43, %46 : tile<64xi32>
    %48 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %49 = broadcast %48 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %50 = offset %49, %47 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %51, %52 = load_ptr_tko weak %50 token=%41 : tile<64xptr<f64>> -> tile<64xf64>, token
    %53 = constant <i32: 1> : tile<i32>
    %54 = addi %5, %53 : tile<i32>
    %55 = reshape %54 : tile<i32> -> tile<1xi32>
    %56 = broadcast %55 : tile<1xi32> -> tile<64xi32>
    %57 = iota : tile<64xi32>
    %58 = constant <i32: 0> : tile<64xi32>
    %59 = muli %57, %58 : tile<64xi32>
    %60 = addi %56, %59 : tile<64xi32>
    %61 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %62 = broadcast %61 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %63 = offset %62, %60 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %64, %65 = load_ptr_tko weak %63 token=%52 : tile<64xptr<f64>> -> tile<64xf64>, token
    %66 = constant <i32: 2> : tile<i32>
    %67 = addi %5, %66 : tile<i32>
    %68 = reshape %67 : tile<i32> -> tile<1xi32>
    %69 = broadcast %68 : tile<1xi32> -> tile<64xi32>
    %70 = iota : tile<64xi32>
    %71 = constant <i32: 0> : tile<64xi32>
    %72 = muli %70, %71 : tile<64xi32>
    %73 = addi %69, %72 : tile<64xi32>
    %74 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %75 = broadcast %74 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %76 = offset %75, %73 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %77, %78 = load_ptr_tko weak %76 token=%65 : tile<64xptr<f64>> -> tile<64xf64>, token
    %79 = subf %51, %16 rounding<nearest_even> : tile<64xf64>
    %80 = subf %64, %28 rounding<nearest_even> : tile<64xf64>
    %81 = subf %77, %40 rounding<nearest_even> : tile<64xf64>
    %82 = mulf %79, %79 rounding<nearest_even> : tile<64xf64>
    %83 = mulf %80, %80 rounding<nearest_even> : tile<64xf64>
    %84 = addf %82, %83 rounding<nearest_even> : tile<64xf64>
    %85 = mulf %81, %81 rounding<nearest_even> : tile<64xf64>
    %86 = addf %84, %85 rounding<nearest_even> : tile<64xf64>
    %87 = constant <i32: 0> : tile<i32>
    %88 = reshape %87 : tile<i32> -> tile<1xi32>
    %89 = broadcast %88 : tile<1xi32> -> tile<64xi32>
    %90 = iota : tile<64xi32>
    %91 = addi %89, %90 : tile<64xi32>
    %92 = reshape %1 : tile<i32> -> tile<1xi32>
    %93 = broadcast %92 : tile<1xi32> -> tile<64xi32>
    %94 = iota : tile<64xi32>
    %95 = constant <i32: 0> : tile<64xi32>
    %96 = muli %94, %95 : tile<64xi32>
    %97 = addi %93, %96 : tile<64xi32>
    %98 = cmpi equal %97, %91, signed : tile<64xi32> -> tile<64xi1>
    %99 = constant <f64: Infinity> : tile<64xf64>
    %100 = select %98, %99, %86 : tile<64xi1>, tile<64xf64>
    %101, %102 = reduce %100, %91 dim=0 identities=[Infinity : f64, -1 : i32] : tile<64xf64>, tile<64xi32> -> tile<f64>, tile<i32> (%103: tile<f64>, %104: tile<f64>, %105: tile<i32>, %106: tile<i32>) {
      %107 = cmpf greater_than ordered %104, %103 : tile<f64> -> tile<i1>
      %108 = select %107, %103, %104 : tile<i1>, tile<f64>
      %109 = select %107, %105, %106 : tile<i1>, tile<i32>
      yield %108, %109 : tile<f64>, tile<i32>
    }
    %110 = constant <i32: 1> : tile<i32>
    %111 = muli %1, %110 : tile<i32>
    %112 = reshape %102 : tile<i32> -> tile<1xi32>
    %113 = broadcast %112 : tile<1xi32> -> tile<1xi32>
    %114 = reshape %111 : tile<i32> -> tile<1xi32>
    %115 = broadcast %114 : tile<1xi32> -> tile<1xi32>
    %116 = iota : tile<1xi32>
    %117 = addi %115, %116 : tile<1xi32>
    %118 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %119 = broadcast %118 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %120 = offset %119, %117 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %121 = store_ptr_tko weak %120, %113 token=%78 : tile<1xptr<i32>>, tile<1xi32> -> token
    return
  }
}
